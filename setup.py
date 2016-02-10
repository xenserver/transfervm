from xcp.supplementalpack import *
from optparse import OptionParser

parser = OptionParser()
parser.add_option('--pln', dest="platform_name")
parser.add_option('--plv', dest="platform_version")
parser.add_option('--bld', dest="build")
parser.add_option('--out', dest="outdir")
(options, args) = parser.parse_args()

xs = Requires(originator='xcp', name='main', test='eq',
               product=options.platform_name, version=options.platform_version,
               build=options.build)

setup(originator='xs', name='xenserver-transfer-vm', product=options.platform_name,
      version=options.platform_version, build=options.build, vendor='Citrix',
      description="XenServer Transfer VM", packages=args, requires=[xs],
      outdir=options.outdir, output=['iso', 'dir'])
