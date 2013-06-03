#!/usr/bin/python
"""This module requires libvhdio support: it assumes the libraries libvhd.so and libvhdio.so
are installed on the system. These libraries are provided by the blktap RPM package."""

import os
import random
import util
import sys
import subprocess
import logging
import re

PATTERN_EMPTY                  = 0
PATTERN_SHORT_STRING_BEGINNING = 1
PATTERN_SHORT_STRING_MIDDLE    = 2
PATTERN_SHORT_STRING_END       = 3
PATTERN_BLOCKS_SEQUENTIAL      = 4
PATTERN_BLOCKS_REVERSE         = 5
PATTERN_BLOCKS_RANDOM          = 6
PATTERN_BLOCKS_RANDOM_FRACTION = 7

LIBVHDIO_PATH = "/usr/lib/libvhdio.so"
VHD_UTIL = "/usr/bin/vhd-util"
#Check if the LIBVHDIO libaray is present - report error if not

if not os.path.isfile(LIBVHDIO_PATH):
	print "Error: " + LIBVHDIO_PATH + " does not exist on this machine"
	sys.exit(0)

LIBVHDIO_CMD = "LD_PRELOAD=" + LIBVHDIO_PATH + " "

BLOCK_SIZE = 4096
VHD_BLOCK_SIZE = 2 * 1024 * 1024
M = 1024 * 1024

PATTERN_FILE = "pattern.tmp"

def _zero(fn, off, len):
     
    if len == 0:
      return

    partial_block = BLOCK_SIZE - (off % BLOCK_SIZE)
    if partial_block % BLOCK_SIZE:
        if partial_block > len:
            partial_block = len
        cmd = "dd conv=notrunc if=/dev/zero of=%s bs=1 seek=%d count=%d" % (fn, off, partial_block)
        util.doexec(cmd, 0)
        off += partial_block
        len -= partial_block

    if len == 0:
        return

    whole_blocks = len / BLOCK_SIZE
    if whole_blocks:
        cmd = "dd conv=notrunc if=/dev/zero of=%s bs=%d seek=%d count=%d" % \
                (fn, BLOCK_SIZE, off / BLOCK_SIZE, whole_blocks)
        util.doexec(cmd, 0)
        off += whole_blocks * BLOCK_SIZE
        len -= whole_blocks * BLOCK_SIZE

    if len == 0:
        return

    cmd = "dd conv=notrunc if=/dev/zero of=%s bs=1 seek=%d count=%d" % (fn, off, len)
    util.doexec(cmd, 0)

def _fill_range(vhd_fn, reference_fn, pattern_fn, off, len, pattern_len, pattern_off):
    if pattern_off < off:
        raise Exception("invalid usage of _fill_range")

 #   _zero(reference_fn, off, pattern_off - off)
    cmd = "dd conv=notrunc if=%s of=%s bs=1 seek=%d" % (pattern_fn, reference_fn, pattern_off)
    util.doexec(cmd, 0)
  #  _zero(reference_fn, pattern_off + pattern_len, len - pattern_len - (pattern_off - off))

    cmd = LIBVHDIO_CMD + "dd if=%s of=%s bs=1 seek=%d" % (pattern_fn, vhd_fn, pattern_off)
    util.doexec(cmd, 0)

def _fill_block(vhd_fn, reference_fn, block, pattern_fn, pattern_len):
    start_off = block * VHD_BLOCK_SIZE
    remaining = VHD_BLOCK_SIZE
    while remaining:
        #print "%d remaining" % remaining
        amount = random.randint(1, 512 * 800) # skip up to 800 sectors
        if amount > remaining:
            amount = remaining
        remaining -= amount
        #print "skip: %d" % amount
   #     _zero(reference_fn, start_off, amount)
        start_off += amount

        rep = random.randint(1, 100) # write up to 100 reps of the pattern sequentially
        #print "write: %d pattern reps" % rep
        for j in range(rep):
            if not remaining:
                break
            amount = pattern_len
            if amount > remaining:
                amount = remaining
            remaining -= amount
            _fill_range(vhd_fn, reference_fn, pattern_fn, start_off, amount, amount, start_off)
            start_off += amount

def zeroReferenceFile(reference_fn, size_mb):
    if os.path.isfile(reference_fn):
         cmdrm = "rm %s" % (reference_fn)
         util.doexec(cmdrm,0)

    cmd = "dd if=/dev/zero of=%s bs=1M count=%d" % (reference_fn, size_mb)
    util.doexec(cmd, 0)
    return



def to_bitmap(blocks, size):
    BIT_MASK = 0x80
    num_blocks = size / VHD_BLOCK_SIZE
    bitmap_size = num_blocks >> 3
    if (bitmap_size << 3) < num_blocks:
        bitmap_size += 1
    bitmap_arr = []
    for i in range(num_blocks):
        if i % 8 == 0:
            bitmap_arr.append(0)
        if i in blocks:
            bitmap_arr[i >> 3] |= (BIT_MASK >> (i & 7));
    bitmap = ""
    for byte in bitmap_arr:
        bitmap += chr(byte)
    return bitmap

def create(path, size_mb):
    cmd = "vhd-util create -n %s -s %d" % (path, size_mb)
    util.doexec(cmd, 0)

def fill(vhd_fn, reference_fn, size_mb, pattern):
    zeroReferenceFile(reference_fn, size_mb) #writing zeroes to reference file to avoid WAW propblem
    size = size_mb * 1024 * 1024
    fraction = 100
    if pattern == PATTERN_EMPTY:
        cmd = "dd if=/dev/zero of=%s bs=1M count=%d" % (reference_fn, size_mb)
        util.doexec(cmd, 0)
        return

    pattern_string = "Random bits here >>%s<< end of random bits" % random.getrandbits(100)
    pattern_len = len(pattern_string)
    f = open(PATTERN_FILE, 'w')
    f.write(pattern_string)
    f.close()

    if pattern == PATTERN_SHORT_STRING_BEGINNING:
        _fill_range(vhd_fn, reference_fn, PATTERN_FILE, 0, size, pattern_len, 0)
    elif pattern == PATTERN_SHORT_STRING_MIDDLE:
        _fill_range(vhd_fn, reference_fn, PATTERN_FILE, 0, size, pattern_len, size / 2)
    elif pattern == PATTERN_SHORT_STRING_END:
        _fill_range(vhd_fn, reference_fn, PATTERN_FILE, 0, size, pattern_len, size - pattern_len)
    elif pattern == PATTERN_BLOCKS_SEQUENTIAL:
        for i in range(size / VHD_BLOCK_SIZE):
            _fill_range(vhd_fn, reference_fn, PATTERN_FILE,
                    i * VHD_BLOCK_SIZE, VHD_BLOCK_SIZE, pattern_len, i * VHD_BLOCK_SIZE + 1000)
    elif pattern == PATTERN_BLOCKS_REVERSE:
        for i in range(size / VHD_BLOCK_SIZE - 1, -1, -1):
            _fill_range(vhd_fn, reference_fn, PATTERN_FILE,
                    i * VHD_BLOCK_SIZE, VHD_BLOCK_SIZE, pattern_len, i * VHD_BLOCK_SIZE + 1000)
    elif pattern == PATTERN_BLOCKS_RANDOM:
        block_seq = range(size / VHD_BLOCK_SIZE)
        random.shuffle(block_seq)
        for i in block_seq:
            print "Populating block %d" % i
            _fill_block(vhd_fn, reference_fn, i, PATTERN_FILE, pattern_len)
    elif pattern == PATTERN_BLOCKS_RANDOM_FRACTION:
        block_seq = range(1, (size / VHD_BLOCK_SIZE), fraction)
        random.shuffle(block_seq)
        for i in block_seq:
            print "Populating block %d" % i
            _fill_block(vhd_fn, reference_fn, i, PATTERN_FILE, pattern_len)
    else:
        raise Exception("Invalid pattern number: %d" % pattern)

    os.unlink(PATTERN_FILE)

def diff(vhd_fn1, vhd_fn2):
    cmd = "vhd-util check -n %s" % (vhd_fn1)
    util.doexec(cmd, 0)
    cmd = "vhd-util check -n %s" % (vhd_fn2)
    util.doexec(cmd, 0)
    cmd = LIBVHDIO_CMD + "diff %s %s" % (vhd_fn1, vhd_fn2)
    return util.doexec(cmd, 0)

def extract(vhd_fn, out_fn):
    cmd = "vhd-util check -n %s" % (vhd_fn)
    util.doexec(cmd, 0)

    cmd = LIBVHDIO_CMD + "dd if=%s of=%s bs=4K" % (vhd_fn, out_fn)
    util.doexec(cmd, 0)


def mask(fn, size, blocks):
    num_blocks = size / VHD_BLOCK_SIZE
    for i in range(num_blocks):
        if i not in blocks:
            _zero(fn, i * VHD_BLOCK_SIZE, VHD_BLOCK_SIZE)


def get_virtual_size(fn):
    """Returns the virtual size of a specified VHD file in MB"""
    process = subprocess.Popen([VHD_UTIL, "query", "-S", "-n", fn],
				stdout=subprocess.PIPE)
    stdout, _ = process.communicate()
    if process.returncode == 0:
	logging.debug('Reading VHD virtual size for %s' % fn)
	return int(stdout)
    else:
	logging.debug('Unable to read virtual vdi size!')
	return -1

def get_block_data(fn, blk):
   """Returns the data inside a specified vhd block"""
   process = subprocess.Popen([VHD_UTIL, "read", "-d", str(blk), "-n", str(fn)],
				stdout=subprocess.PIPE)
   stdout, _ = process.communicate()
   if process.returncode == 0:
	logging.debug('Reading the contents of block %s in file %s' % (blk, fn))
        return stdout
   else:
	logging.debug('Unable to return data')
	return -1

def get_bitmap(fn, blk):
   """Returns the bitmap contents for a given block"""
   process = subprocess.Popen([VHD_UTIL, "read", "-m", str(blk), "-n", str(fn)],
				stdout=subprocess.PIPE)
   stdout, _ = process.communicate()
   if process.returncode == 0:
	logging.debug('Reading the Bitmap from blk %s in file %s' % (blk, fn))

	x = re.compile("block*")
	if not re.match(x, stdout):
		return stdout
	else:
		return None
   else:
	logging.debug('Unable to read the from blk %s in file %s' % (blk, fn))
	return -1

def check_if_bitmap_full(bitmap):
   """Given a bitmap, returns true if every sector is used, and false otherwise"""
   full_bitmap = "\xff" * 512 #Each bitmap is 512 bits
   return bitmap == full_bitmap

def get_non_filled_blocks(fn):
   """Given a VHD file, the function returns non-filled blocks"""
   blocks = get_allocated_blocks(fn)
   non_filled_bitmaps = []
   for block in blocks:
	bitmap = get_bitmap(fn,block)
	if not check_if_bitmap_full(bitmap):
		non_filled_bitmaps.append(block)
   return non_filled_bitmaps	


def get_allocated_blocks(fn):
    """Returns a list of allocated VHD blocks in the specified vhd"""    
    file_size = get_virtual_size(fn) * M
    num_blocks = file_size / VHD_BLOCK_SIZE
    logging.debug("File size %d" % (file_size))
    logging.debug("Number of blocks %d" % (num_blocks))
    allocated = []
    for block in range(num_blocks):
        process = subprocess.Popen([VHD_UTIL, "read", "-b", str(block), "-n", fn],
                                   stdout=subprocess.PIPE)
        stdout, _ = process.communicate()
        if process.returncode == 0:
	    if (not re.search("not allocated", stdout)) and re.search("offset", stdout):
		allocated.append(block)
        else:
            logging.debug("Error, unable to read block %d" % (block))

    return allocated

def compare_vhd_data(fn1, fn2):
    """Compares the block data between two vhds ignoring the bitmaps and headers"""
    alloc_fn1 = get_allocated_blocks(fn1)
    alloc_fn2 = get_allocated_blocks(fn2)
    
    #Check that they both have the same number of block - fail if not
    if(alloc_fn1 != alloc_fn2):
	raise Exception("The vhd's being compared, %s and %s, do not have the same number of allocated blocks!" % (fn1, fn2))
    else:
	#Renaming to make easier to follow
	alloc_blocks = alloc_fn1
	
    non_matching_blocks = [] 

    for block in alloc_blocks:
	#print "Comparing block number %s" % block
	data_fn1 = get_block_data(fn1, block)
	data_fn2 = get_block_data(fn2, block)

	if data_fn1 != data_fn2:
		print "Non matching block %s" % block
		non_matching_blocks.append(block)
    
    if non_matching_blocks != []:
	return non_matching_blocks
    else:
	return
