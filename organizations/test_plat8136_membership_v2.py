"""PLAT-5343 slice 1 — Admin v2 membership composition (HLD v12 §4.3).

Pins the ID→Admin trust boundary, the composition parity rules, the snapshot
validation, and the dependency proof (§10 gate 3 Admin half: exactly one local
query + exactly one Pulse v2 call).

Negative-authentication matrix rows for the ID→Admin hop (S2): tokenless,
tenant bearer, wrong-service credential, wrong audience/scope, expired,
future iat, alg violations, invalid sub, header↔credential mismatch (S4),
confused-deputy body identity, replayed jti, unconfigured fail-closed.

Composition parity (§4.3): ``is_active=True`` required; ``is_pending`` and
organization activity NOT reinterpreted; Admin row matches on non-null
``user_id == sub``; asserted-email fallback only for ``user_id IS NULL`` rows;
a conflicting non-null user ID matched by email is denied + counted (the ONLY
deliberate v1/v2 difference). Candidate authorized iff its org is in the local
Admin set OR the subject-bound Pulse roster evidence. Every failure mode is a
typed non-200 — never ``200 + []``.
"""
import time
import uuid
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from organizations.models import Organization, OrganizationMembership
from organizations.membership_v2 import (
    SNAPSHOT_SCHEMA,
    _subject_fingerprint,
    resolve_local_admin_orgs,
)

ID_CREDENTIAL = 'v2-hop-credential-id'
PULSE_CREDENTIAL = 'v2-hop-credential-pulse'


def _generate_signing_key():
    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return key, pub.decode('ascii')


def _id_assertion(signing_key, *, sub=4242, email='zen@shizuha.com', issuer='shizuha-id',
                  audience='shizuha-admin', scope='membership-projection:resolve',
                  iat=None, exp=None, lifetime=5, jti=None, claims_override=None):
    now = int(time.time())
    iat = now if iat is None else iat
    exp = iat + lifetime if exp is None else exp
    claims = {
        'iss': issuer, 'aud': audience, 'scope': scope, 'sub': str(sub),
        'iat': iat, 'exp': exp, 'jti': jti or str(uuid.uuid4()),
    }
    if email is not None:
        claims['email'] = email
    if claims_override:
        claims.update(claims_override)
    pem = signing_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return jwt.encode(claims, pem, algorithm='EdDSA')


def _snapshot_body(sub=4242, email='zen@shizuha.com', candidates=None,
                   roster_org_evidence=None, fingerprint=None, schema=SNAPSHOT_SCHEMA,
                   generated_at=None, valid_for_ms=500):
    from django.utils import timezone
    if fingerprint is None:
        fingerprint = _subject_fingerprint('shizuha-admin', sub, email)
    return {
        'schema': schema,
        'subject_fingerprint': fingerprint,
        'snapshot_id': str(uuid.uuid4()),
        'generated_at': generated_at or timezone.now().isoformat().replace('+00:00', 'Z'),
        'valid_for_ms': valid_for_ms,
        'candidates': candidates if candidates is not None else [],
        'roster_org_evidence': roster_org_evidence or [],
    }


V2_SETTINGS = override_settings(
    ADMIN_V2_INTERNAL_SERVICE_CREDENTIALS={'shizuha-id': ID_CREDENTIAL},
    ADMIN_V2_PULSE_SERVICE_CREDENTIAL=PULSE_CREDENTIAL,
)


class _V2CompositionTestCase(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.id_key, cls.id_public_pem = _generate_signing_key()
        cls.admin_key, cls.admin_public_pem = _generate_signing_key()

    def setUp(self):
        super().setUp()
        self.url = reverse('internal-v2-project-memberships-resolve')
        self._settings = V2_SETTINGS
        self._settings.enable()
        self.addCleanup(self._settings.disable)
        self._key_override = override_settings(
            ADMIN_V2_ID_SIGNING_PUBLIC_KEYS=[self.id_public_pem],
            ADMIN_V2_SIGNING_PRIVATE_KEY=self._admin_private_pem(),
        )
        self._key_override.enable()
        self.addCleanup(self._key_override.disable)

    def _admin_private_pem(self):
        return self.admin_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode('ascii')

    def _post(self, assertion=None, body=None, service='shizuha-id',
              credential=ID_CREDENTIAL, pulse_response=None, pulse_exception=None,
              pulse_status=200):
        """POST with a mocked Pulse v2 response (or exception)."""
        captured = {}

        def fake_post(url, **kwargs):
            captured['url'] = url
            captured['kwargs'] = kwargs
            if pulse_exception is not None:
                raise pulse_exception
            class _Resp:
                status_code = pulse_status
                def json(self):
                    return pulse_response
            return _Resp()

        headers = {}
        if service is not None:
            headers['HTTP_X_INTERNAL_SERVICE'] = service
        if credential is not None:
            headers['HTTP_X_INTERNAL_SERVICE_TOKEN'] = credential
        if assertion is not None:
            headers['HTTP_X_SHIZUHA_SUBJECT_ASSERTION'] = assertion
        with patch('organizations.membership_v2.http_requests.post', side_effect=fake_post):
            response = self.client.post(self.url, data=body, format='json', **headers)
        response.captured_pulse = captured
        return response


class V2NegativeAuthenticationMatrixTests(_V2CompositionTestCase):
    """One test per §4.1 rejection clause (S2 matrix, ID→Admin hop)."""

    def test_01_tokenless_request_rejected(self):
        response = self._post(assertion=None, service=None, credential=None)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['reason'], 'missing_headers')

    def test_02_tenant_bearer_token_is_not_service_proof(self):
        tenant_jwt = _id_assertion(self.id_key, issuer='shizuha-id',
                                   audience='shizuha-api', scope='openid')
        response = self.client.post(
            self.url, format='json', HTTP_AUTHORIZATION=f'Bearer {tenant_jwt}')
        self.assertEqual(response.status_code, 401)
        self.assertNotIn('project_memberships', response.json())

    def test_03_wrong_service_credential_rejected(self):
        """The Admin-issued credential (unknown principal) on this hop."""
        response = self._post(
            _id_assertion(self.id_key), service='shizuha-admin',
            credential='admin-credential')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['reason'], 'unknown_caller')

    def test_04_wrong_audience_rejected(self):
        response = self._post(_id_assertion(self.id_key, audience='shizuha-pulse'))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['reason'], 'wrong_audience')

    def test_05_wrong_scope_rejected(self):
        response = self._post(_id_assertion(
            self.id_key, scope='project-membership-candidates:resolve'))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['reason'], 'wrong_scope')

    def test_06_expired_assertion_rejected(self):
        now = int(time.time())
        response = self._post(_id_assertion(self.id_key, iat=now - 6, exp=now - 5))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['reason'], 'expired')

    def test_07_future_iat_rejected(self):
        now = int(time.time())
        response = self._post(_id_assertion(self.id_key, iat=now + 60, exp=now + 65))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['reason'], 'future_iat')

    def test_08a_alg_none_rejected(self):
        token = jwt.encode(
            {'iss': 'shizuha-id', 'aud': 'shizuha-admin',
             'scope': 'membership-projection:resolve', 'sub': '4242',
             'iat': int(time.time()), 'exp': int(time.time()) + 5,
             'jti': str(uuid.uuid4())},
            key='', algorithm='none')
        response = self._post(token)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['reason'], 'algorithm_not_allowed')

    def test_08b_hs256_confusion_rejected(self):
        token = jwt.encode(
            {'iss': 'shizuha-id', 'aud': 'shizuha-admin',
             'scope': 'membership-projection:resolve', 'sub': '4242',
             'iat': int(time.time()), 'exp': int(time.time()) + 5,
             'jti': str(uuid.uuid4())},
            key='shared-secret-confusion', algorithm='HS256')
        response = self._post(token)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['reason'], 'algorithm_not_allowed')

    def test_08c_wrong_key_signature_rejected(self):
        other_key, other_pem = _generate_signing_key()
        assertion = _id_assertion(self.id_key)
        with override_settings(ADMIN_V2_ID_SIGNING_PUBLIC_KEYS=[other_pem]):
            response = self._post(assertion)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['reason'], 'bad_signature')

    def test_09_invalid_subjects_rejected_before_lookup(self):
        for bad_sub in (0, -1, 'abc', None, True):
            with self.subTest(sub=bad_sub):
                response = self._post(_id_assertion(self.id_key, sub=bad_sub))
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()['reason'], 'invalid_subject')

    def test_10_header_credential_mismatch_rejected(self):
        """S4: a configured credential presented under another service name."""
        two_credentials = override_settings(
            ADMIN_V2_INTERNAL_SERVICE_CREDENTIALS={
                'shizuha-id': ID_CREDENTIAL,
                'shizuha-admin': 'v2-hop-credential-admin',
            },
        )
        with two_credentials:
            response = self._post(_id_assertion(self.id_key), service='shizuha-admin')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['reason'], 'credential_mismatch')

    def test_11_confused_deputy_body_identity_rejected(self):
        for body in ({'sub': 9999}, {'email': 'attacker@shizuha.com'},
                     {'user_id': 9999}):
            with self.subTest(body=body):
                response = self._post(_id_assertion(self.id_key), body=body)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()['reason'], 'caller_supplied_identity')

    def test_replayed_jti_rejected(self):
        jti = str(uuid.uuid4())
        first = self._post(_id_assertion(self.id_key, jti=jti),
                           pulse_response=_snapshot_body())
        self.assertEqual(first.status_code, 200)
        replay = self._post(_id_assertion(self.id_key, jti=jti),
                            pulse_response=_snapshot_body())
        self.assertEqual(replay.status_code, 401)
        self.assertEqual(replay.json()['reason'], 'replayed_jti')

    def test_lifetime_exceeded_rejected(self):
        response = self._post(_id_assertion(self.id_key, lifetime=30))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['reason'], 'lifetime_exceeded')

    def test_stated_clock_skew_tolerated(self):
        now = int(time.time())
        within = self._post(_id_assertion(self.id_key, iat=now + 1, exp=now + 6),
                            pulse_response=_snapshot_body())
        self.assertEqual(within.status_code, 200)
        slightly_past = self._post(
            _id_assertion(self.id_key, iat=now - 6, exp=now - 1),
            pulse_response=_snapshot_body())
        self.assertEqual(slightly_past.status_code, 200)

    def test_unconfigured_route_fails_closed(self):
        with override_settings(ADMIN_V2_INTERNAL_SERVICE_CREDENTIALS={},
                               ADMIN_V2_ID_SIGNING_PUBLIC_KEYS=[]):
            response = self._post(_id_assertion(self.id_key))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['reason'], 'not_configured')


class V2CompositionParityTests(_V2CompositionTestCase):
    """§4.3 composition + exact parity with the current semantics."""

    def setUp(self):
        super().setUp()
        self.org1 = Organization.objects.create(name='One', slug='one', owner_id=1, is_active=True)
        self.org2 = Organization.objects.create(name='Two', slug='two', owner_id=1, is_active=True)
        self.org3 = Organization.objects.create(name='Three', slug='three', owner_id=1, is_active=True)

    def _assertion(self, sub=4242, email='zen@shizuha.com'):
        return _id_assertion(self.id_key, sub=sub, email=email)

    def test_local_admin_membership_authorizes_candidate(self):
        OrganizationMembership.objects.create(
            organization_id=self.org1.id, user_id=4242, is_active=True)
        snapshot = _snapshot_body(candidates=[
            {'project_id': 342, 'organization_id': self.org1.id, 'role': 'member'}])
        response = self._post(self._assertion(), pulse_response=snapshot)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'project_memberships': {'342': 'member'},
            'project_ids': [342],
        })

    def test_roster_evidence_authorizes_candidate_without_admin_membership(self):
        """Roster-only fleet-agent path preserved (ADR-0069 option F)."""
        snapshot = _snapshot_body(roster_org_evidence=[
            {'organization_id': self.org2.id, 'roster_rows': [{'id': 17, 'version': 12}]}],
            candidates=[
                {'project_id': 350, 'organization_id': self.org2.id, 'role': 'viewer'}])
        response = self._post(self._assertion(), pulse_response=snapshot)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'project_memberships': {'350': 'viewer'},
            'project_ids': [350],
        })

    def test_foreign_org_evidence_never_authorizes(self):
        """Candidate org in neither the Admin set nor roster evidence → denied."""
        OrganizationMembership.objects.create(
            organization_id=self.org1.id, user_id=4242, is_active=True)
        snapshot = _snapshot_body(candidates=[
            {'project_id': 342, 'organization_id': self.org1.id, 'role': 'member'},
            {'project_id': 999, 'organization_id': self.org3.id, 'role': 'member'},
        ])
        response = self._post(self._assertion(), pulse_response=snapshot)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'project_memberships': {'342': 'member'},
            'project_ids': [342],
        })

    def test_email_fallback_only_for_null_user_id_rows(self):
        OrganizationMembership.objects.create(
            organization_id=self.org1.id, user_id=None, user_email='zen@shizuha.com',
            is_active=True)
        snapshot = _snapshot_body(candidates=[
            {'project_id': 342, 'organization_id': self.org1.id, 'role': 'member'}])
        response = self._post(self._assertion(), pulse_response=snapshot)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['project_ids'], [342])

    def test_conflicting_non_null_user_id_email_row_denied_and_counted(self):
        """The ONLY permitted deliberate difference vs v1 (§4.4 step 2)."""
        OrganizationMembership.objects.create(
            organization_id=self.org1.id, user_id=9999, user_email='zen@shizuha.com',
            is_active=True)
        snapshot = _snapshot_body(candidates=[
            {'project_id': 342, 'organization_id': self.org1.id, 'role': 'member'}])
        response = self._post(self._assertion(), pulse_response=snapshot)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'project_memberships': {},
            'project_ids': [],
        })

    def test_inactive_membership_row_never_authorizes(self):
        OrganizationMembership.objects.create(
            organization_id=self.org1.id, user_id=4242, is_active=False)
        snapshot = _snapshot_body(candidates=[
            {'project_id': 342, 'organization_id': self.org1.id, 'role': 'member'}])
        response = self._post(self._assertion(), pulse_response=snapshot)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['project_ids'], [])

    def test_is_pending_not_reinterpreted(self):
        """§4.3: is_pending is NOT silently reinterpreted — v1 parity."""
        membership = OrganizationMembership.objects.create(
            organization_id=self.org1.id, user_id=4242, is_active=True)
        if hasattr(membership, 'is_pending'):
            membership.is_pending = True
            membership.save(update_fields=['is_pending'])
        snapshot = _snapshot_body(candidates=[
            {'project_id': 342, 'organization_id': self.org1.id, 'role': 'member'}])
        response = self._post(self._assertion(), pulse_response=snapshot)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['project_ids'], [342])

    def test_authoritative_empty_is_valid_200(self):
        response = self._post(self._assertion(), pulse_response=_snapshot_body())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'project_memberships': {}, 'project_ids': []})

    def test_null_org_candidate_never_authorizes(self):
        snapshot = _snapshot_body(candidates=[
            {'project_id': 342, 'organization_id': None, 'role': 'member'}])
        response = self._post(self._assertion(), pulse_response=snapshot)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['project_ids'], [])


class V2SnapshotValidationTests(_V2CompositionTestCase):
    """Stale, duplicate-conflicting, or malformed evidence → typed 502."""

    def setUp(self):
        super().setUp()
        self.org1 = Organization.objects.create(name='One', slug='one', owner_id=1, is_active=True)

    def _assertion(self):
        return _id_assertion(self.id_key)

    def test_unknown_schema_rejected(self):
        snapshot = _snapshot_body(schema='shizuha.pulse.something.v1')
        response = self._post(self._assertion(), pulse_response=snapshot)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()['reason'], 'unknown_schema')

    def test_fingerprint_mismatch_rejected(self):
        snapshot = _snapshot_body(fingerprint='sha256:' + '0' * 64)
        response = self._post(self._assertion(), pulse_response=snapshot)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()['reason'], 'fingerprint_mismatch')

    def test_stale_snapshot_rejected(self):
        from django.utils import timezone
        import datetime as dt
        old = timezone.now() - dt.timedelta(seconds=120)
        snapshot = _snapshot_body(
            generated_at=old.isoformat().replace('+00:00', 'Z'))
        response = self._post(self._assertion(), pulse_response=snapshot)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()['reason'], 'stale_snapshot')

    def test_duplicate_project_candidate_rejected(self):
        snapshot = _snapshot_body(candidates=[
            {'project_id': 342, 'organization_id': self.org1.id, 'role': 'member'},
            {'project_id': 342, 'organization_id': self.org1.id, 'role': 'viewer'},
        ])
        response = self._post(self._assertion(), pulse_response=snapshot)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()['reason'], 'duplicate_project_candidate')

    def test_malformed_candidate_rejected(self):
        snapshot = _snapshot_body(candidates=[{'project_id': '342', 'organization_id': 1}])
        response = self._post(self._assertion(), pulse_response=snapshot)
        self.assertEqual(response.status_code, 502)

    def test_malformed_roster_evidence_rejected(self):
        snapshot = _snapshot_body(roster_org_evidence=[
            {'organization_id': 1, 'roster_rows': [{'id': 1}]},  # missing version
        ])
        response = self._post(self._assertion(), pulse_response=snapshot)
        self.assertEqual(response.status_code, 502)

    def test_pulse_non_200_is_typed_503_never_empty_200(self):
        response = self._post(self._assertion(), pulse_status=503)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('project_memberships', response.json())

    def test_pulse_timeout_is_typed_503(self):
        import requests as http_requests
        response = self._post(
            self._assertion(),
            pulse_exception=http_requests.Timeout('pulse read timeout'))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['error'], 'project_membership_unavailable')

    def test_pulse_unparseable_body_is_typed_502(self):
        class _Resp:
            status_code = 200
            def json(self):
                raise ValueError('not json')
        with patch('organizations.membership_v2.http_requests.post', return_value=_Resp()):
            response = self.client.post(
                self.url, format='json',
                HTTP_X_INTERNAL_SERVICE='shizuha-id',
                HTTP_X_INTERNAL_SERVICE_TOKEN=ID_CREDENTIAL,
                HTTP_X_SHIZUHA_SUBJECT_ASSERTION=self._assertion())
        self.assertEqual(response.status_code, 502)


class V2DerivativeAssertionTests(_V2CompositionTestCase):
    """The Admin→Pulse derivative binds the parent and carries a fresh jti."""

    def setUp(self):
        super().setUp()
        self.org1 = Organization.objects.create(name='One', slug='one', owner_id=1, is_active=True)

    def test_derivative_claims_and_parent_hash(self):
        parent = _id_assertion(self.id_key, sub=4242, email='zen@shizuha.com')
        snapshot = _snapshot_body(candidates=[
            {'project_id': 342, 'organization_id': self.org1.id, 'role': 'member'}])
        response = self._post(parent, pulse_response=snapshot)
        self.assertEqual(response.status_code, 200)

        derivative = response.captured_pulse['kwargs']['headers'][
            'X-Shizuha-Subject-Assertion']
        # Verify under Admin's public key with the S1 allowlist.
        admin_public = self.admin_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        claims = jwt.decode(
            derivative, admin_public, algorithms=['EdDSA'],
            options={'verify_exp': False, 'verify_iat': False,
                     'verify_sub': False, 'verify_aud': False})
        self.assertEqual(claims['iss'], 'shizuha-admin')
        self.assertEqual(claims['aud'], 'shizuha-pulse')
        self.assertEqual(claims['scope'], 'project-membership-candidates:resolve')
        self.assertEqual(claims['sub'], '4242')
        self.assertEqual(claims['email'], 'zen@shizuha.com')
        import hashlib
        self.assertEqual(
            claims['parent_assertion_sha256'],
            hashlib.sha256(parent.encode('utf-8')).hexdigest())
        self.assertLessEqual(claims['exp'] - claims['iat'], 5)
        # Fresh jti: never the parent's.
        parent_claims = jwt.decode(
            parent, self.id_public_pem, algorithms=['EdDSA'],
            options={'verify_exp': False, 'verify_iat': False,
                     'verify_sub': False, 'verify_aud': False})
        self.assertNotEqual(claims['jti'], parent_claims['jti'])

    def test_pulse_call_shape(self):
        """Exactly one Pulse call, correct route + bound credential header."""
        response = self._post(_id_assertion(self.id_key), pulse_response=_snapshot_body())
        self.assertEqual(response.status_code, 200)
        captured = response.captured_pulse
        self.assertEqual(captured['kwargs']['headers']['X-Internal-Service'],
                         'shizuha-admin')
        self.assertEqual(captured['kwargs']['headers']['X-Internal-Service-Token'],
                         PULSE_CREDENTIAL)
        self.assertTrue(captured['url'].endswith(
            '/internal/v2/project-membership-candidates:resolve'))


class V2DependencyProofTests(_V2CompositionTestCase):
    """§10 gate 3 (Admin half): exactly one local query + one Pulse call."""

    def setUp(self):
        super().setUp()
        self.org1 = Organization.objects.create(name='One', slug='one', owner_id=1, is_active=True)
        OrganizationMembership.objects.create(
            organization_id=self.org1.id, user_id=4242, is_active=True)

    def test_exactly_one_local_query_and_one_pulse_call(self):
        from django.test.utils import CaptureQueriesContext
        from django.db import connection
        calls = []
        org1_id = self.org1.id

        def fake_post(url, **kwargs):
            calls.append(url)
            class _Resp:
                status_code = 200
                def json(self):
                    return _snapshot_body(candidates=[
                        {'project_id': 342, 'organization_id': org1_id,
                         'role': 'member'}])
            return _Resp()

        with patch('organizations.membership_v2.http_requests.post',
                   side_effect=fake_post):
            with CaptureQueriesContext(connection) as ctx:
                response = self.client.post(
                    self.url, format='json',
                    HTTP_X_INTERNAL_SERVICE='shizuha-id',
                    HTTP_X_INTERNAL_SERVICE_TOKEN=ID_CREDENTIAL,
                    HTTP_X_SHIZUHA_SUBJECT_ASSERTION=_id_assertion(self.id_key))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(calls), 1, calls)
        # Membership-table queries issued by the composition path itself.
        membership_queries = [
            q for q in ctx.captured_queries
            if 'organizations_membership' in q['sql']
        ]
        self.assertEqual(len(membership_queries), 1, ctx.captured_queries)


class LocalAdminOrgResolutionTests(_V2CompositionTestCase):
    """Unit pins for the single-query partition (§4.3 matching rules)."""

    def test_partition_rules(self):
        org_a = Organization.objects.create(name='A', slug='a', owner_id=1, is_active=True)
        org_b = Organization.objects.create(name='B', slug='b', owner_id=1, is_active=True)
        org_c = Organization.objects.create(name='C', slug='c', owner_id=1, is_active=True)
        org_d = Organization.objects.create(name='D', slug='d', owner_id=1, is_active=True)
        OrganizationMembership.objects.create(
            organization_id=org_a.id, user_id=4242, is_active=True)  # exact sub
        OrganizationMembership.objects.create(
            organization_id=org_b.id, user_id=None, user_email='zen@shizuha.com',
            is_active=True)  # email fallback, null user_id
        OrganizationMembership.objects.create(
            organization_id=org_c.id, user_id=9999, user_email='zen@shizuha.com',
            is_active=True)  # conflicting non-null user_id
        OrganizationMembership.objects.create(
            organization_id=org_d.id, user_id=4242, is_active=False)  # inactive

        admin_orgs, conflicts = resolve_local_admin_orgs(4242, 'zen@shizuha.com')
        self.assertEqual(admin_orgs, {org_a.id, org_b.id})
        self.assertEqual(conflicts, 1)

    def test_no_email_means_no_email_fallback(self):
        org_a = Organization.objects.create(name='A', slug='a2', owner_id=1, is_active=True)
        OrganizationMembership.objects.create(
            organization_id=org_a.id, user_id=None, user_email='zen@shizuha.com',
            is_active=True)
        admin_orgs, conflicts = resolve_local_admin_orgs(4242, None)
        self.assertEqual(admin_orgs, set())
        self.assertEqual(conflicts, 0)
