package tensorboard

import "hash/crc32"

// crc32cTable is the table to use for computing a CRC-32C checksum.
//
// CRC-32C is a CRC-32 with the Castagnoli polynomial, which is used for the
// checksums in tfevents files:
// https://github.com/tensorflow/tensorboard/blob/ae7d0b9250f5986dd0f0c238fcaf3c8d7f4312ca/tensorboard/compat/tensorflow_stub/pywrap_tensorflow.py#L157-L165
var crc32cTable = crc32.MakeTable(crc32.Castagnoli)

// MaskedCRC32C computes the "masked" CRC32-C checksum used in tfevents files.
//
// I don't know why it's done this way, but it comes from here:
// https://github.com/tensorflow/tensorboard/blob/ae7d0b9250f5986dd0f0c238fcaf3c8d7f4312ca/tensorboard/compat/tensorflow_stub/pywrap_tensorflow.py#L39-L41
func MaskedCRC32C(data []byte) uint32 {
	checksum := crc32.Checksum(data, crc32cTable)
	return ((checksum >> 15) | (checksum << 17)) + 0xA282EAD8
}
