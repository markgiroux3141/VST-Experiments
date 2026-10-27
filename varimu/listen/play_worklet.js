// The Play page's audio: blocks from the server (float32, mono) into a ring
// buffer, played out on both channels. Starts once PREFILL is buffered; an empty
// buffer plays silence and counts a dropout. Reports the samples played so far
// (the server keeps a fixed amount of audio ahead of that) every REPORT samples.

const SIZE = 1 << 18;      // ring buffer, samples (~5 s at 48 kHz)
const PREFILL = 4800;      // 100 ms at 48 kHz before playing
const REPORT = 1024;

class StreamPlayer extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buf = new Float32Array(SIZE);
    this.w = 0; this.r = 0;              // samples written / read so far
    this.started = false; this.dropouts = 0; this.inDropout = false;
    this.sinceReport = 0;
    this.port.onmessage = e => {
      const a = new Float32Array(e.data);
      for (let i = 0; i < a.length; i++) this.buf[(this.w + i) & (SIZE - 1)] = a[i];
      this.w += a.length;
    };
  }

  process(inputs, outputs) {
    const out = outputs[0], n = out[0].length;
    if (!this.started && this.w - this.r >= PREFILL) this.started = true;
    for (let i = 0; i < n; i++) {
      let v = 0;
      if (this.started && this.r < this.w) { v = this.buf[this.r & (SIZE - 1)]; this.r++; this.inDropout = false; }
      else if (this.started && !this.inDropout) { this.dropouts++; this.inDropout = true; }
      for (const ch of out) ch[i] = v;
    }
    this.sinceReport += n;
    if (this.sinceReport >= REPORT) {
      this.sinceReport = 0;
      this.port.postMessage({ consumed: this.r, dropouts: this.dropouts });
    }
    return true;
  }
}

registerProcessor('stream-player', StreamPlayer);
