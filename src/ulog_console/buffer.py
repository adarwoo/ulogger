# This file is part of the ulog_console project.
# It is subject to the license terms in the LICENSE file found in the top-level directory of this distribution.

class PersistantIndexCircularBuffer:
    def __init__(self, maxlen):
        self.maxlen = maxlen
        self.buffer = [None] * maxlen
        self.abs_indexes = [None] * maxlen
        self.start = 0  # points to oldest
        self.end = 0    # points to next insert
        self.size = 0
        self.next_abs_index = 0

    def append(self, item):
        self.buffer[self.end] = item
        self.abs_indexes[self.end] = self.next_abs_index
        self.end = (self.end + 1) % self.maxlen

        if self.size < self.maxlen:
            self.size += 1
        else:
            self.start = (self.start + 1) % self.maxlen

        self.next_abs_index += 1

    def __len__(self):
        return self.size

    def head_abs_index(self):
        if self.size == 0:
            return None
        return self.abs_indexes[self.start]

    def tail_abs_index(self):
        if self.size == 0:
            return None
        return self.abs_indexes[(self.end - 1) % self.maxlen]

    def slice_by_abs_index(self, start_abs, count):
        # Returns a list of items starting at start_abs for count items
        result = []
        if self.size == 0:
            return result
        head = self.head_abs_index()
        tail = self.tail_abs_index()
        if start_abs < head:
            start_abs = head
        if start_abs > tail:
            return result
        idx = start_abs - head
        for i in range(count):
            buf_idx = (self.start + idx + i) % self.maxlen
            cur_abs = head + idx + i
            if cur_abs > tail or i >= self.size:
                break
            result.append(self.buffer[buf_idx])
        return result

    def latest_slice(self, count):
        # Returns the latest count items
        if self.size == 0:
            return []
        start_idx = max(0, self.size - count)
        result = []
        for i in range(start_idx, self.size):
            buf_idx = (self.start + i) % self.maxlen
            result.append(self.buffer[buf_idx])
        return result