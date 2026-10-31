"""Exercise installer decisions without sudo, network, or desktop mutations."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / 'packaging/install.sh'

class InstallerTests(unittest.TestCase):
    def shell(self, code, home=None):
        return subprocess.run(['bash', '-c', 'source "$1"\n' + code, 'test', str(INSTALLER)],
                              env={**os.environ, **({'HOME': str(home)} if home else {})},
                              text=True, capture_output=True)

    def test_distro_package_plans(self):
        for distro, version, manager in [('cachyos','','pacman'), ('arch','','pacman'),
                ('ubuntu','24.04','apt-get'), ('ubuntu','26.04','apt-get'),
                ('debian','13','apt-get'), ('linuxmint','22.1','apt-get')]:
            with self.subTest(distro=distro):
                result = self.shell(f'select_packages {distro} "{version}"; echo "$manager ${{packages[*]}}"')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(manager, result.stdout)
                self.assertIn('mpd', result.stdout)
                self.assertIn('wireplumber', result.stdout)

    def test_old_or_unknown_distributions_stop(self):
        for distro, version in [('ubuntu','22.04'),('debian','12'),('fedora','44')]:
            result = self.shell(f'select_packages {distro} {version}; echo SHOULD_NOT_RUN')
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('SHOULD_NOT_RUN', result.stdout)

    def test_sourcing_does_not_install(self):
        result = self.shell('echo sourced')
        self.assertEqual(result.stdout, 'sourced\n')

    def test_pipe_entrypoint_and_dry_run_are_non_mutating(self):
        with tempfile.TemporaryDirectory() as home:
            result = subprocess.run(['bash','-s','--','--dry-run'], input=INSTALLER.read_text(),
                text=True, capture_output=True, env={**os.environ,'HOME':home})
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('System packages',result.stdout)
            self.assertEqual(list(Path(home).iterdir()), [])

    def test_existing_configuration_is_preserved(self):
        with tempfile.TemporaryDirectory() as home:
            path = Path(home)/'.config/mpd/mpd.conf'
            path.parent.mkdir(parents=True)
            path.write_text('existing player configuration')
            result = self.shell('systemctl() { [[ $1 != is-active ]]; }; export DISPLAY=:test; install_main --skip-system --music-dir /tmp', home)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('configuration already exists',result.stderr)
            self.assertEqual(path.read_text(),'existing player configuration')

    def test_bad_download_does_not_create_environment(self):
        with tempfile.TemporaryDirectory() as home:
            result = self.shell('''
                systemctl() { [[ $1 != is-active ]]; }
                pactl() { echo 'PulseAudio (on PipeWire)'; }
                curl() { return 22; }
                export DISPLAY=:test
                install_main --skip-system --music-dir /tmp
            ''', home)
            self.assertNotEqual(result.returncode,0)
            self.assertFalse((Path(home)/'.local/share/ampere/venv').exists())

    def test_checksum_failure_does_not_install(self):
        with tempfile.TemporaryDirectory() as home:
            result = self.shell('''
                systemctl() { [[ $1 != is-active ]]; }
                pactl() { echo 'PulseAudio (on PipeWire)'; }
                curl() { while (($#)); do if [[ $1 == -o ]]; then printf tampered > "$2"; return; fi; shift; done; }
                export DISPLAY=:test
                install_main --skip-system --music-dir /tmp
            ''', home)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('FAILED',result.stdout)
            self.assertFalse((Path(home)/'.local/share/ampere/venv').exists())

if __name__ == '__main__':
    unittest.main()
