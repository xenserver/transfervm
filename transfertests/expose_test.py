
import logging
import threading
import time
import unittest

import testsetup
import transferclient
import moreasserts
import XenAPI


M = 1024 * 1024

def clean_up():
    hostname = testsetup.HOST
    testsetup.clean_host(hostname)

class ExposeThread(threading.Thread):
    def __init__(self, hostname, network, vdi, transfer_mode='http', target_host_uuid=None):
        threading.Thread.__init__(self)
        self.hostname = hostname
        self.network = network
        self.vdi = vdi
        self.transfer_mode = transfer_mode
        self.target_host_uuid = target_host_uuid

    def run(self):
        kwargs = {}
        kwargs['hostname'] = self.hostname
        kwargs['network_uuid'] = self.network
        kwargs['vdi_uuid'] = self.vdi
        kwargs['transfer_mode'] = self.transfer_mode
        if self.target_host_uuid:
            kwargs['target_host_uuid'] = self.target_host_uuid
        transferclient.expose(**kwargs)

def nice():
    return 1

class AssertReturningExposeThread(ExposeThread):
    def __init__(self, hostname, network, vdi, testinstance, output_list):
        threading.Thread.__init__(self)
        self.hostname = hostname
        self.network = network
        self.vdi = vdi
        self.testinstance = testinstance
        self.output_list = output_list

    def run(self):
        try:
            moreasserts.assertRaisesXenapiFailure(self.testinstance, 'ConfigurationError', transferclient.expose,
                self.hostname, vdi_uuid=self.vdi, network_uuid=self.network, transfer_mode='http')
        except Exception, e:
            # threading.Thread does not provide run() return values or exceptions to the caller.
            # Return the exception via output_list.
            # TODO: It would be nicer to use some third-party python library for background tasks that handle this.
            self.output_list.append(e)
            return
        self.output_list.append(None)

@transferclient.xenapi_session
def stop_running_vms(session, host):
    for vm, vmrec in session.xenapi.VM.get_all_records_where('field "is_a_template" = "false" and field "is_control_domain" = "false" and field "power_state" = "Running"').items():
        if 'transfervm_clone' in vmrec['other_config']:
            session.xenapi.VM.hard_shutdown(vm)
            logging.debug('Stopped VM %r' % vmrec['name_label'])
        else:
            logging.debug('Skipped VM %r' % str(vmrec['other_config']))

@transferclient.xenapi_session
def get_host_uuids(session, host):
    return session.xenapi.host.get_by_name_label(host)

class ExposeConfigurationTest(unittest.TestCase):
    TRANSFER_MODE = "http"
    REMOVE_TEMPLATE = False
    
    def testTargetHostUUIDConfig(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)
        if self.REMOVE_TEMPLATE:
            #Remove the TVM template to catch errors that would occur on first run (when the template doesn't exist)
            testsetup.remove_tvm_template(hostname)
        host_uuid = get_host_uuids(hostname)
        transfer_mode=self.TRANSFER_MODE
        asyncexpose = ExposeThread(hostname, network, vdi, transfer_mode=transfer_mode, target_host_uuid=host_uuid)
        asyncexpose.start()
        while asyncexpose.isAlive():
            time.sleep(1)
        record = transferclient.get_record(hostname, vdi_uuid=vdi)
        logging.debug(record)
        transferclient.unexpose(hostname, vdi_uuid=vdi)
        testsetup.clean_host(hostname)

class ExposeConfigurationTestRemoveTVMTemplate(ExposeConfigurationTest):
    REMOVE_TEMPLATE = True

class ExposeConcurrencyTest(unittest.TestCase):
    def testExposeWhileHammeringCleanup(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)
        asyncexpose = ExposeThread(hostname, network, vdi)
        asyncexpose.start()
        # Assumes that transferclient.expose is slow.
        while asyncexpose.isAlive():
            logging.debug('Cleaning up')
            transferclient.cleanup(hostname)
            time.sleep(0.0001)

        record = transferclient.get_record(hostname, vdi_uuid=vdi)
        moreasserts.assertVdiIsZeroUsingHttpGet(self, record, 10)

    def testParallelExposes(self):
        parallelism = 3
        hostname, network, firstvdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)

        vdis = [firstvdi] + [transferclient.create_vdi(hostname, 'Test VDI', 10*M) for i in xrange(parallelism - 1)]
        threads = [ExposeThread(hostname, network, vdi) for vdi in vdis]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        records = [transferclient.get_record(hostname, vdi_uuid=vdi) for vdi in vdis]
        for record in records:
            moreasserts.assertVdiIsZeroUsingHttpGet(self, record, 10)

    def testExposeWithParallelGetRecord(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)
        asyncexpose = ExposeThread(hostname, network, vdi)
        asyncexpose.start()

        record = {'status': 'unused'}
        while record['status'] == 'unused':
            logging.debug('VDI status still unused, getting record')
            record = transferclient.get_record(hostname, vdi_uuid=vdi)

        moreasserts.assertVdiIsZeroUsingHttpGet(self, record, 10)

    def testUnexposeWaitsUntilPartialExposeHasFinished(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)
        asyncexpose = ExposeThread(hostname, network, vdi)
        asyncexpose.start()

        response = None
        while not response:
            logging.debug('VDI status still unused, unexposing')
            try:
                response = transferclient.unexpose(hostname, vdi_uuid=vdi)
            except XenAPI.Failure, e:
                if e.details[2] != 'VDINotInUse':
                    raise
        self.assertEqual('OK', response)
        logging.debug('VDI unexpose succeeded')
        self.assertEqual('unused', transferclient.get_record(hostname, vdi_uuid=vdi)['status'])

    def testExposeRaisesConfigurationErrorIfVMFailsToReportIPAddress(self):
        logging.info('This is a flaky test, as it depends on the Transfer VM startup and DHCP response ' +
                     'being slow enough to find and hard_shutdown this VM before the IP is reported.')

        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10, dangerous_test=True)
        output = []
        asyncexpose = AssertReturningExposeThread(hostname, network, vdi, self, output)
        asyncexpose.start()

        while asyncexpose.isAlive():
            stop_running_vms(hostname)
            time.sleep(0.0001)

        self.assertEqual(1, len(output))
        if output[0] is not None:
            if isinstance(output[0], Exception):
                raise output[0]
            else:
                self.fail('Got unexpected output from async expose thread: %r' % output[0])











