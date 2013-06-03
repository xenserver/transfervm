from xcp.supplementalpack import *
from optparse import OptionParser

parser = OptionParser()
parser.add_option('--pdn', dest="product_name")
parser.add_option('--pdv', dest="product_version")
parser.add_option('--bld', dest="build")
parser.add_option('--out', dest="outdir")
(options, args) = parser.parse_args()

xs = Requires(originator='xs', name='main', test='eq', 
               product=options.product_name, version=options.product_version, 
               build=options.build)

setup(originator='xs', name='xenserver-transfer-vm', product=options.product_name, 
      version=options.product_version, build=options.build, vendor='Citrix', 
      description="XenServer Transfer VM", packages=args, requires=[xs],
      outdir=options.outdir, output=['iso', 'dir'])
