# This file is part of OpenStack Ansible driver for Kostyor.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import sys

import mock
import pytest

from kostyor.rpc import app, tasks
from kostyor_openstack_ansible.upgrades import alt

from ..common import get_fixture, get_inventory_instance, get_hosts


class TestDriver(object):

    _inventory = get_fixture('dynamic_inventory.json')

    @pytest.fixture(autouse=True)
    def use_sync_tasks(self, monkeypatch):
        monkeypatch.setattr(app.app.conf, 'CELERY_ALWAYS_EAGER', True)

    @pytest.fixture(autouse=True)
    def use_fake_inventory(self, monkeypatch):
        monkeypatch.setattr(
            'kostyor_openstack_ansible.upgrades.alt.Inventory',
            mock.Mock(
                return_value=get_inventory_instance(self._inventory)
            )
        )

    @pytest.fixture(autouse=True)
    def use_fake_popen(self, monkeypatch):
        self.popen = mock.Mock()
        self.popen.return_value.returncode = 0

        monkeypatch.setattr(
            sys.modules['kostyor.rpc.tasks.execute'].subprocess,
            'Popen',
            self.popen
        )

    def setup(self):
        self.driver = alt.Driver()

    @mock.patch('kostyor.rpc.tasks.execute.si', return_value=tasks.noop.si())
    def test_pre_upgrade(self, execute):
        self.driver.pre_upgrade()()

        execute.assert_called_once_with(
            '/opt/openstack-ansible/scripts/bootstrap-ansible.sh',
            cwd='/opt/openstack-ansible')

        assert self.popen.call_args_list == [
            mock.call(
                [
                    '/usr/local/bin/openstack-ansible',
                    (
                        '/opt/openstack-ansible/scripts/upgrade-utilities'
                        '/playbooks/ansible_fact_cleanup.yml'
                    )
                ],
                cwd=None),
            mock.call(
                [
                    '/usr/local/bin/openstack-ansible',
                    (
                        '/opt/openstack-ansible/scripts/upgrade-utilities'
                        '/playbooks/deploy-config-changes.yml'
                    )
                ],
                cwd=None),
            mock.call(
                [
                    '/usr/local/bin/openstack-ansible',
                    (
                        '/opt/openstack-ansible/scripts/upgrade-utilities'
                        '/playbooks/user-secrets-adjustment.yml'
                    )
                ],
                cwd=None),
            mock.call(
                [
                    '/usr/local/bin/openstack-ansible',
                    (
                        '/opt/openstack-ansible/scripts/upgrade-utilities'
                        '/playbooks/pip-conf-removal.yml'
                    )
                ],
                cwd=None),
            mock.call(
                [
                    '/usr/local/bin/openstack-ansible',
                    '/opt/openstack-ansible/playbooks/repo-install.yml'
                ],
                cwd='/opt/openstack-ansible/playbooks'),
        ]

    def test_start_runs_playbook(self):
        self.driver.start({'name': 'nova-compute'}, get_hosts('compute1'))()

        self.popen.assert_called_once_with(
            [
                '/usr/local/bin/openstack-ansible',
                '/opt/openstack-ansible/playbooks/os-nova-install.yml',
                '-l',
                'compute1',
            ],
            cwd=None,
        )

    def test_start_runs_playbook_on_few_hosts(self):
        self.driver.start(
            {'name': 'horizon-wsgi'}, get_hosts('infra1', 'infra2'))()

        self.popen.assert_called_once_with(
            [
                '/usr/local/bin/openstack-ansible',
                '/opt/openstack-ansible/playbooks/os-horizon-install.yml',
                '-l',
                ','.join([
                    'infra1_horizon_container-afb604da',
                    'infra2_horizon_container-b7a45742',
                ]),
            ],
            cwd=None,
        )

    def test_start_upgrade_runs_playbook_once_on_one_host(self):
        hosts = get_hosts('infra2')

        self.driver.start({'name': 'nova-api'}, hosts)()
        self.driver.start({'name': 'nova-conductor'}, hosts)()

        assert self.popen.call_args[0][0][0:3] == [
            '/usr/local/bin/openstack-ansible',
            '/opt/openstack-ansible/playbooks/os-nova-install.yml',
            '-l',
        ]

        assert set(self.popen.call_args[0][0][3].split(',')) == set([
            'infra2_nova_api_metadata_container-a542f3a5',
            'infra2_nova_api_os_compute_container-d088a5c5',
            'infra2_nova_cert_container-f4bebee6',
            'infra2_nova_conductor_container-c9d5c8ec',
            'infra2_nova_console_container-14f4435d',
            'infra2_nova_scheduler_container-ea104a41',
        ])

    def test_start_runs_playbook_once_on_few_hosts(self):
        host1, host2 = get_hosts('infra1', 'infra2')

        # The second .start(...) must trigger playbook only for host2 as
        # host1 was upgrades by first call.
        self.driver.start({'name': 'nova-api'}, [host1])()
        self.driver.start({'name': 'nova-conductor'}, [host1, host2])()

        assert self.popen.call_args[0][0][0:3] == [
            '/usr/local/bin/openstack-ansible',
            '/opt/openstack-ansible/playbooks/os-nova-install.yml',
            '-l',
        ]

        assert set(self.popen.call_args[0][0][3].split(',')) == set([
            'infra2_nova_api_metadata_container-a542f3a5',
            'infra2_nova_api_os_compute_container-d088a5c5',
            'infra2_nova_cert_container-f4bebee6',
            'infra2_nova_conductor_container-c9d5c8ec',
            'infra2_nova_console_container-14f4435d',
            'infra2_nova_scheduler_container-ea104a41',
        ])

    def test_start_upgrade_skip_not_supported_service(self):
        self.driver.start({'name': 'unknown-service'}, get_hosts('infra1'))()

        self.popen.assert_not_called()

    def test_raise_exception_on_error(self):
        self.popen.return_value.returncode = 42

        with pytest.raises(Exception) as excinfo:
            self.test_start_runs_playbook()

        excinfo.match(
            r'Command \'/usr/local/bin/openstack-ansible '
            r'/opt/openstack-ansible/playbooks/os-nova-install.yml -l '
            r'compute1\' returned non-zero exit status 42\.?')
