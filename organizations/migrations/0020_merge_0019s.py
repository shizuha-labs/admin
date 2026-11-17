from django.db import migrations


class Migration(migrations.Migration):
    """Content-neutral join node for the two organizations 0019 leaves.

    The branch adds 0019_waiver_issuance_grant (SCS-256, load-bearing grant
    ordering for SCS-256 — do not renumber) while main carries its own
    0019_orig412_pending_dispatch_status. Two leaves in the organizations
    graph refuse `migrate` during test-DB creation, killing the authz gate
    before any test runs (33s face, run 733 job `authz-test-gate`).

    Join node pattern per fleet numbered-merge precedent (sara/pulse#336
    0206_merge_plat4182_branch_with_main.py).
    """

    dependencies = [
        ('organizations', '0019_orig412_pending_dispatch_status'),
        ('organizations', '0019_waiver_issuance_grant'),
    ]

    operations = []
