
import logging
import sys
import time
import unittest
import xml.sax.saxutils

class _XmlTestResult(unittest.TestResult):
    """A test result class that can print formatted text results to a stream.

    Used by XmlTestRunner.
    """

    def __init__(self, xmlstream=sys.stdout):
        unittest.TestResult.__init__(self)
        self.stream = unittest._WritelnDecorator(xmlstream)
        self.successes = []  # unittest.TestResult does not store successes

    def startTest(self, test):
        unittest.TestResult.startTest(self, test)
        logging.info(str(test) + ' ...')

    def addSuccess(self, test):
        unittest.TestResult.addSuccess(self, test)
        self.successes.append(test)
        logging.info('OK')

    def addError(self, test, err):
        unittest.TestResult.addError(self, test, err)
        logging.info('ERROR')

    def addFailure(self, test, err):
        unittest.TestResult.addFailure(self, test, err)
        logging.info('FAIL')

    def output_xml(self):
        self.stream.writeln('<?xml version="1.0" ?>')
        self.stream.writeln('<results>')
        for test in self.successes:
            self.output_test(test, 'pass')
        for test, err in self.errors:
            self.output_test(test, 'error', err)
        for test, err in self.failures:
            self.output_test(test, 'fail', err)
        self.stream.writeln('</results>')

    def output_test(self, test, state, err=None):
        self.output_header(test)
        self.output_state(state)
        if err:
            self.output_log(err)
        self.stream.writeln('  </test>')

    def output_header(self, test):
        self.stream.writeln('  <test>')
        self.stream.writeln('    <name>')
        self.stream.writeln('      ' + self.get_name(test))
        self.stream.writeln('    </name>')
        self.stream.writeln('    <group>')
        self.stream.writeln('      <name>')
        self.stream.writeln('        ' + self.get_group(test))
        self.stream.writeln('      </name>')
        self.stream.writeln('    </group>')

    def output_state(self, state):
        self.stream.writeln('    <state>')
        self.stream.writeln('      ' + state)
        self.stream.writeln('    </state>')

    def output_log(self, err):
        self.stream.writeln('    <log>')
        self.stream.writeln('      ' + xml.sax.saxutils.escape(err))
        self.stream.writeln('    </log>')

    def get_name(self, test):
        return test.id().rsplit('.', 1)[1]

    def get_group(self, test):
        return test.id().rsplit('.', 1)[0]

class XmlTestRunner(object):
    """A test runner class that displays results in XML form.

    It logs test names and results to stderr as they are run, and
    prints an XML-formatted status report to stdout when done.
    """
    def __init__(self, stream=sys.stdout):
        self.stream = stream

    def run(self, test):
        "Run the given test case or test suite."

        # Run tests and gather results
        result = _XmlTestResult(self.stream)
        startTime = time.time()
        test(result)
        stopTime = time.time()
        timeTaken = stopTime - startTime

        result.output_xml()

        # Log errors and a summary
        self.print_error_list('ERROR', result.errors)
        self.print_error_list('FAIL', result.failures)

        run = result.testsRun
        logging.info('Ran %d test%s in %.3fs' % (run, run != 1 and 's' or '', timeTaken))
        if not result.wasSuccessful():
            summary = 'FAILED ('
            failed, errored = map(len, (result.failures, result.errors))
            if failed:
                summary += 'failures=%d' % failed
            if errored:
                if failed:
                    summary += ', '
                summary += 'errors=%d' % errored
            logging.info(summary)
        else:
            logging.info('OK')

        return result

    separator1 = '=' * 70
    separator2 = '-' * 70

    def print_error_list(self, tag, testlist):
        for test, err in testlist:
            logging.info(self.separator1)
            logging.info('%s: %s' % (tag, str(test)))
            logging.info(self.separator2)
            logging.info(str(err))
