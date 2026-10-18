"""Use the approved bench harness with a dedicated disposable test profile."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from verify_compatibility import verify_report

source = Path(os.environ['GITHUB_WORKSPACE']).resolve()
temporary = Path(os.environ['RUNNER_TEMP']).resolve()
support = temporary / 'doctype-acceptance-support'
shutil.copytree(source / 'ci-support/.github/ci', support)
catalog_path = support / 'public-apps.json'
catalog = json.loads(catalog_path.read_text())
catalog['doctype_permission']['test_dependencies'] = ['hrms']
catalog_path.write_text(json.dumps(catalog, indent=2) + '\n')
for app in ('frappe', 'erpnext', 'hrms'):
    assert len(catalog[app]['ci_sha']) == 40, 'Acceptance dependencies must be pinned'

# Compose the standard seed and the app's synthetic HRMS fixture. The immutable
# helper is copied into RUNNER_TEMP; shared support and application code stay intact.
(support / 'site_seed.py').rename(support / 'standard_site_seed.py')
(support / 'site_seed.py').write_text(
    'import runpy\n'
    f'runpy.run_path({str(support / "standard_site_seed.py")!r}, run_name="__main__")\n'
    f'runpy.run_path({str(source / ".github/ci/seed_compatibility.py")!r}, run_name="__main__")\n')

config_path = source / '.github/dinext-ci.json'
original = config_path.read_bytes()
config = json.loads(original)
assert config['app'] == 'doctype_permission'
config.update(mode='frappe-app', skip_test_records=False)
provenance = {'repository': os.environ['GITHUB_REPOSITORY'],
    'tested_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip(),
    'event': os.environ['GITHUB_EVENT_NAME'],
    'dependencies': {app: catalog[app] for app in ('frappe', 'erpnext', 'hrms')}}
(temporary / 'compatibility-environment.json').write_text(json.dumps(provenance, indent=2) + '\n')
try:
    config_path.write_text(json.dumps(config, indent=2) + '\n')
    subprocess.run([sys.executable, str(support / 'bench_tests.py'), str(source)], check=True)
    count = verify_report(temporary / 'doctype_permission-unit.xml')
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
        summary.write(f'\n### Compatibility acceptance\n\n{count} executed tests passed on '
            f'`{provenance["tested_revision"]}` against pinned Frappe/ERPNext/HRMS 15.\n')
finally:
    config_path.write_bytes(original)
