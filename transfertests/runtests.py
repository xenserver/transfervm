#!/usr/bin/python
""" Wrapper around unittest.main() to parse extra arguments and store global options for the tests."""

import logging
import optparse
import sys
import re
import unittest

import testsetup
import xmltestoutput


MODULES = ['expose_test', 'timeout_test', 'manualnetwork_test', 'bits_test', 'http_test', 'unexpose_test', 'getrecord_test', 'expose_failure_test', 'vhd_tests', 'copy_plugin']

def load_tests(opts, args):
    suite = unittest.TestSuite()
    if args:
        # Load specified tests
        suite.addTest(unittest.defaultTestLoader.loadTestsFromNames(args))
    else:
        # Load all tests
        suite.addTest(unittest.defaultTestLoader.loadTestsFromNames(MODULES))
    return suite


def run_tests(opts, args, suite):
    # Write deployment configuration to globals in the testsetup module.
    # This is a horrible architecture, but it would be worse to hack the unittest module to
    # pass the opts or args into TestCase.run invocations, and this module's globals cannot
    # be used because it is named __main__, not runtests in the interpreter when running
    # this as a script.
    testsetup.HOST = opts.host
    if opts.plugin:
        testsetup.PLUGIN = opts.plugin
    if opts.xenapi:
        testsetup.XENAPI = opts.xenapi
    if opts.template:
        testsetup.VMTEMPLATE = opts.template
    if opts.wipe:
        testsetup.WIPE_HOST = True

    if opts.text:
        runner = unittest.TextTestRunner(verbosity=opts.verbose + 1)
    else:
        runner = xmltestoutput.XmlTestRunner()
    result = runner.run(suite)
    sys.exit(not result.wasSuccessful())


def getnames(test):
    if isinstance(test, unittest.TestCase):
        return [test.id()]
    else:
        names = []
        for subtest in test._tests:
            names.extend(getnames(subtest))
        return names

def parsemodulename(module):
    return ' '.join(map(str.capitalize, module.split('_')[:-1]))

def parseclassname(klass):
    return ' '.join(re.findall(r'[A-Z0-9][a-z]+|[A-Z0-9]+(?=[A-Z0-9]|$)', klass)[:-1])

def parsemethodname(method):
    return ' '.join(re.findall(r'[A-Z0-9][a-z]+|[A-Z0-9]+(?=[A-Z0-9]|$)', method))

def parsename(name):
    module, klass, method = name.split('.')
    section = '%s - %s Tests' % (parsemodulename(module), parseclassname(klass))
    return section, parsemethodname(method)

def print_docs(opts, args, suite):
    names = map(parsename, getnames(suite))
    sections = set(section for section, method in names)
    for section in sections:
        print
        print section
        for name in names:
            if name[0] == section:
                print '    ' + name[1]


if __name__ == '__main__':
    parser = optparse.OptionParser(usage='usage: %prog [options] [test module, class or method]')
    parser.add_option('-v', '--verbose', dest='verbose', action='count', default=0,
                    help='Increase verbosity (specify multiple times for more)')
    parser.add_option('--docs', dest='docs', action='store_true', default=False, help='Print a sentence-formatted list of all tests that would be run, but do not run them.')
    parser.add_option('--text', dest='text', action='store_true', default=False, help='Output test progress and results in the standard Python unittest format.')
    parser.add_option('--xml', dest='xml', action='store_true', default=False, help='Output test results in XenSource XML format, and log test progress to stderr.')

    parser.add_option('--host', dest='host', help='Hostname to run tests on.')
    parser.add_option('--wipe-host', dest='wipe', action='store_true', default=False, help='Whether to wipe the host before starting.  DESTRUCTIVE!')
    parser.add_option('--plugin', dest='plugin', help='Path to the Transfer plugin file for deployment. Optional; will use version on server if not supplied).')
    parser.add_option('--plugin-xenapi', dest='xenapi', help='Path to the XenAPIPlugin.py file for deployment. Optional; will use version on server if not supplied).')
    parser.add_option('--vm-template', dest='template', help='Path to the Transfer VM .xva file for deployment. Optional; will use version on server if not supplied.')

    opts, args = parser.parse_args()

    log_level = logging.WARNING # default
    if opts.verbose == 1:
        log_level = logging.INFO
    elif opts.verbose >= 2:
        log_level = logging.DEBUG

    # Set up basic configuration, out to stderr with a reasonable default format.
    logging.basicConfig(level=log_level)

    if not opts.docs and not opts.text and not opts.xml:
        parser.error('An action is required: either --docs, or running tests in --text or --xml format.')
        sys.exit(1)
    else:
        suite = load_tests(opts, args)

        if opts.docs:
            print_docs(opts, args, suite)
        else:
            if not opts.host:
                parser.error('--host is required for running tests.')
            run_tests(opts, args, suite)


