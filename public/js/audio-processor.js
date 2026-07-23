class Float32ToInt16Processor extends AudioWorkletProcessor {
    constructor() {
        super();
        this._buffer = new Float32Array(0);
        this.port.onmessage = (e) => {
            if (e.data === 'flush' && this._buffer.length > 0) {
                this.port.postMessage({ audio: this._buffer });
                this._buffer = new Float32Array(0);
            }
        };
    }

    process(inputs) {
        var input = inputs[0];
        if (!input || !input[0]) return true;
        var channelData = input[0];
        var newBuf = new Float32Array(this._buffer.length + channelData.length);
        newBuf.set(this._buffer);
        newBuf.set(channelData, this._buffer.length);
        this._buffer = newBuf;

        if (this._buffer.length >= 4096) {
            this.port.postMessage({ audio: this._buffer });
            this._buffer = new Float32Array(0);
        }
        return true;
    }
}

registerProcessor('float32-to-int16-processor', Float32ToInt16Processor);
