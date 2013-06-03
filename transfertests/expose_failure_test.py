#!/usr/bin/python

import logging
import unittest

import moreasserts
import testsetup
import transferclient
import XenAPI


class VMTemplateErrorTest(unittest.TestCase):
    def assertRaisesConfigurationError(self, method, *args, **kwargs):
        moreasserts.assertRaisesXenapiFailure(self, 'ConfigurationError', method, *args, **kwargs)

    def testExposeRaisesConfigurationErrorIfTransferVMTemplateIsMissing(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=0, vdi_mb=10)
        self.assertRaisesConfigurationError(transferclient.expose,
                                            hostname,
                                            vdi_uuid=vdi,
                                            network_uuid=network,
                                            transfer_mode='http')

    def testExposeRaisesConfigurationErrorIfTwoTransferVMTemplatesAreFound(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=2, vdi_mb=10)
        self.assertRaisesConfigurationError(transferclient.expose,
                                            hostname,
                                            vdi_uuid=vdi,
                                            network_uuid=network,
                                            transfer_mode='http')


class InvalidArgumentsTest(unittest.TestCase):
    def assertRaisesArgumentError(self, method, *args, **kwargs):
        moreasserts.assertRaisesXenapiFailure(self, 'ArgumentError', method, *args, **kwargs)

    def testExposeRaisesArgumentErrorIfTransferModeIsMissing(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)
        self.assertRaisesArgumentError(transferclient.expose,
                                            hostname,
                                            vdi_uuid=vdi,
                                            network_uuid=network)

    def testExposeRaisesArgumentErrorIfVdiUuidIsMissing(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)
        self.assertRaisesArgumentError(transferclient.expose,
                                            hostname,
                                            network_uuid=network,
                                            transfer_mode='http')

    def testExposeRaisesArgumentErrorIfNetworkUuidIsMissing(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)
        self.assertRaisesArgumentError(transferclient.expose,
                                            hostname,
                                            vdi_uuid=vdi,
                                            transfer_mode='http')

    def testExposeRaisesArgumentErrorIfTransferModeIsInvalid(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)
        self.assertRaisesArgumentError(transferclient.expose,
                                            hostname,
                                            vdi_uuid=vdi,
                                            network_uuid=network,
                                            transfer_mode='carrierpigeons')

    def testExposeRaisesArgumentErrorIfNetworkModeIsInvalid(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)
        self.assertRaisesArgumentError(transferclient.expose,
                                            hostname,
                                            vdi_uuid=vdi,
                                            network_uuid=network,
                                            transfer_mode='http',
                                            network_mode='randomsetup')

    def testExposeRaisesArgumentErrorIfUseSslIsInvalid(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)
        self.assertRaisesArgumentError(transferclient.expose,
                                            hostname,
                                            vdi_uuid=vdi,
                                            network_uuid=network,
                                            transfer_mode='http',
                                            use_ssl='maybe')

    def testExposeRaisesArgumentErrorIfNetworkPortIsInvalid(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)
        self.assertRaisesArgumentError(transferclient.expose,
                                            hostname,
                                            vdi_uuid=vdi,
                                            network_uuid=network,
                                            transfer_mode='http',
                                            network_port='notanumber')
        self.assertRaisesArgumentError(transferclient.expose,
                                            hostname,
                                            vdi_uuid=vdi,
                                            network_uuid=network,
                                            transfer_mode='http',
                                            network_port='-12345')

    def testExposeRaisesArgumentErrorIfNetworkPortIsNot3260ForISCSITransferMode(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)
        self.assertRaisesArgumentError(transferclient.expose,
                                            hostname,
                                            vdi_uuid=vdi,
                                            network_uuid=network,
                                            transfer_mode='iscsi',
                                            network_port='80')
        self.assertRaisesArgumentError(transferclient.expose,
                                            hostname,
                                            vdi_uuid=vdi,
                                            network_uuid=network,
                                            transfer_mode='iscsi',
                                            network_port='3261')

    def testExposeRaisesArgumentErrorIfTimeoutIsNotAnInteger(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)
        self.assertRaisesArgumentError(transferclient.expose,
                                            hostname,
                                            vdi_uuid=vdi,
                                            network_uuid=network,
                                            transfer_mode='http',
                                            timeout_minutes='dozen')

    def testExposeRaisesArgumentErrorIfTimeoutIsNegative(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)
        self.assertRaisesArgumentError(transferclient.expose,
                                            hostname,
                                            vdi_uuid=vdi,
                                            network_uuid=network,
                                            transfer_mode='http',
                                            timeout_minutes='-60')

    def testExposeRaisesArgumentErrorIfNetworkIpIsMissingForManualMode(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)
        self.assertRaisesArgumentError(transferclient.expose,
                                            hostname,
                                            vdi_uuid=vdi,
                                            network_uuid=network,
                                            transfer_mode='http',
                                            network_mode='manual',
                                            network_mask='255.255.255.0',
                                            network_gateway='192.168.1.1')

    def testExposeRaisesArgumentErrorIfNetworkMaskIsMissingForManualMode(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)
        self.assertRaisesArgumentError(transferclient.expose,
                                            hostname,
                                            vdi_uuid=vdi,
                                            network_uuid=network,
                                            transfer_mode='http',
                                            network_mode='manual',
                                            network_ip='192.168.1.42',
                                            network_gateway='192.168.1.1')

    def testExposeRaisesArgumentErrorIfNetworkGatewayIsMissingForManualMode(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)
        self.assertRaisesArgumentError(transferclient.expose,
                                            hostname,
                                            vdi_uuid=vdi,
                                            network_uuid=network,
                                            transfer_mode='http',
                                            network_mode='manual',
                                            network_ip='192.168.1.42',
                                            network_mask='255.255.255.0')

    def testExposeRaisesArgumentErrorIfArgumentsHaveInvalidCharacters(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)
        self.assertRaisesArgumentError(transferclient.expose,
                                            hostname,
                                            vdi_uuid=vdi + '@',
                                            network_uuid=network,
                                            transfer_mode='http')
        # network_mac has no additional validation except allowed characters
        self.assertRaisesArgumentError(transferclient.expose,
                                            hostname,
                                            vdi_uuid=vdi,
                                            network_uuid=network,
                                            transfer_mode='http',
                                            network_mac='%')
        self.assertRaisesArgumentError(transferclient.expose,
                                            hostname,
                                            vdi_uuid=vdi,
                                            network_uuid=network,
                                            transfer_mode='http',
                                            network_mac='a a')
        self.assertRaisesArgumentError(transferclient.expose,
                                            hostname,
                                            vdi_uuid=vdi,
                                            network_uuid=network,
                                            transfer_mode='http',
                                            network_mac='a"')
        self.assertRaisesArgumentError(transferclient.expose,
                                            hostname,
                                            vdi_uuid=vdi,
                                            network_uuid=network,
                                            transfer_mode='http',
                                            network_mac="a'")
        self.assertRaisesArgumentError(transferclient.expose,
                                            hostname,
                                            vdi_uuid=vdi,
                                            network_uuid=network,
                                            transfer_mode='http',
                                            network_mac='a\\')

    def testExposeRaisesArgumentErrorIfArgumentStartsWithMinus(self):
        hostname, network, vdi = testsetup.setup_host_and_network(templates=1, vdi_mb=10)
        self.assertRaisesArgumentError(transferclient.expose,
                                            hostname,
                                            vdi_uuid=vdi,
                                            network_uuid=network,
                                            transfer_mode='http',
                                            network_mac='-otherwiseok')
        self.assertRaisesArgumentError(transferclient.expose,
                                            hostname,
                                            vdi_uuid=vdi,
                                            network_uuid=network,
                                            transfer_mode='http',
                                            network_mac='--otherwiseok')
