import struct
import os

# TODO: rewrite writing code

class IVFHeader:
    def __init__(self, stream):
        (
            self.signature,
            self.version,
            self.header_size,
            self.fourcc,
            self.width,
            self.height,
            self.fps_num,
            self.fps_den,
            self.frame_count,
            self.reserved
        ) = struct.unpack('<4sHH4sHHIII4s', stream.read(32))

class IVFFrameHeader:
    def __init__(self, stream):
        (self.size, self.timestamp) = struct.unpack('<IQ', stream.read(12))

class IVFFile(IVFHeader):
    def __init__(self, file):
        stream = open(file, "rb") if isinstance(file, str) else file
        super().__init__(stream)
        #self._read_header()
        self.frame_offset = []
        self.frame_headers = [] 
        offset = 32
        for _ in range(self.frame_count):
            stream.seek(offset)
            frame_header = IVFFrameHeader(stream)
            self.frame_headers.append(frame_header)
            offset += 12 + frame_header.size

    def get_section_size(self, start_frame=0, end_frame=0):
        if end_frame == 0:
            end_frame = self.frame_count

        num_frames = end_frame - start_frame
        if num_frames == 0:
            return 0
        
        section_size = 0
        for frame_header in self.frame_headers[start_frame:end_frame]:
            section_size += frame_header.size
        return section_size

    def get_frame_size(self):
        section_size = 0
        for frame_header in self.frame_headers:
            section_size += frame_header.size
        return section_size

    def get_section_bitrate(self, start_frame=0, end_frame=0):
        num_frames = end_frame - start_frame
        if num_frames == 0:
            return 0
        return self.get_section_size(start_frame, end_frame) * 8 * (self.fps_num / self.fps_den) / num_frames / 1000

    def get_bitrate(self):
        return self.get_frame_size() * 8 * (self.fps_num / self.fps_den) / self.frame_count / 1000

def read_from_offset(file_path, offset, size):
    with open(file_path, 'rb') as file:
        file.seek(offset)
        data = file.read(size)
    return data

def write_ivf_header(file, width, height, fps_num, fps_den, frame_count=0):
    print(frame_count)
    header = struct.pack(
        '<4sHH4sHHIII4s',
        b'DKIF',        # Signature                             0x00
        0,              # Version                               0x04
        32,             # Header size (don't change this)       0x06
        b'AV01',        # Codec FourCC                          0x08
        width,          # Width                                 0x0C
        height,         # Height                                0x0E
        fps_num,        # Framerate numerator                   0x10
        fps_den,        # Framerate denominator                 0x14
        frame_count,    # Number of frames (can be 0 initially) 0x18
        b'\0\0\0\0'     # Reserved                              0x1C
        # Follows array of frame headers
    )
    file.write(header)

def rewrite_frame_header(file, size, timestamp):
    frame_header = struct.pack(
        '<IQ',
        size,     # 0x00
        timestamp # 0x04
    )
    file.write(frame_header)

def has_all_frames(ivf_path):
    num_frames = int.from_bytes(read_from_offset(ivf_path, 24, 4), 'little')
    offset = 32 # Frame data start
    with open(ivf_path, "rb") as f:
        try:
            for i in range(num_frames):
                f.seek(offset)                                # Jump to header
                size = int.from_bytes(f.read(4), 'little')    # Get size of frame data
                offset += 12 + size                           # Size of frame + size of frame header
        except:
            return False
    
    return True

def split_ivf(ivf_path, keyframes, out_dir):
    # TODO: not tested
    num_frames = int.from_bytes(read_from_offset(ivf_path, 24, 4), 'little')

    framedata = b''
    with open(ivf_path, "rb") as fr:
        start_frame = 0
        offset = 32 # Frame data start
        for i, keyframe in enumerate(keyframes):
            for seek_frame in range(start_frame, num_frames): # Rewrite timestamps
                frame_data_offset = offset + 12
                fr.seek(offset)                                # Jump to header
                size = int.from_bytes(fr.read(4), 'little')    # Get size of frame data
                offset += 12 + size                            # Size of frame + size of frame header
                framedata += read_from_offset(ivf_path, frame_data_offset, size)
                if seek_frame == keyframe:
                    with open(f"{out_dir}/{i:00005}.ivf") as fw:
                        write_ivf_header(fw, 1920, 1080, 24000, 1001, keyframe - start_frame)
                        fw.write(framedata)
                        write_offset = 32 # Frame data start
                        for frame in range(num_frames):                    # Rewrite timestamps
                            fw.seek(write_offset)                          # Jump to header
                            size = int.from_bytes(fw.read(4), 'little')    # Get size of frame data
                            fw.write(frame.to_bytes(8, "little"))          # Rewrite the timestamp
                            write_offset += 12 + size                      # Size of frame + size of frame header
                    start_frame = keyframe
                    break

def merge_chunks(ivf_out_path: str, input_files: list[str], width: int, height: int, fps_num: int, fps_den: int):
    num_frames = 0
    framedata = b''
    i = 0
    for ivf_path in input_files:
        if not os.path.exists(ivf_path):
            print(f"Error! {ivf_path} not found")
            # TODO: error handling
            return

        num_frames += int.from_bytes(read_from_offset(ivf_path, 24, 4), 'little')
        framedata += read_from_offset(ivf_path, 32, -1)
        i += 1

    with open(ivf_out_path, "wb+") as f:
        write_ivf_header(f, width, height, fps_num, fps_den, num_frames)
        f.write(framedata)
        offset = 32 # Frame data start
        for i in range(num_frames): # Rewrite timestamps
            f.seek(offset)                                # Jump to header
            size = int.from_bytes(f.read(4), 'little')    # Get size of frame data
            f.write(i.to_bytes(8, "little"))              # Rewrite the timestamp
            offset += 12 + size                           # Size of frame + size of frame header
