(function () {
    var VOSK_WS_URL = 'ws://localhost:2700';
    var SAMPLE_RATE = 16000;
    var WORKLET_URL = '/js/audio-processor.js';

    function VoiceRecorder() {
        this.ws = null;
        this.context = null;
        this.source = null;
        this.workletNode = null;
        this.stream = null;
        this.recording = false;
        this.onPartial = null;
        this.onResult = null;
        this.onError = null;
        this._resolve = null;
        this._reject = null;
    }

    VoiceRecorder.prototype.start = function () {
        var self = this;
        if (self.recording) return Promise.reject(new Error('Уже записывается'));

        return new Promise(function (resolve, reject) {
            self._resolve = resolve;
            self._reject = reject;

            try {
                self.ws = new WebSocket(VOSK_WS_URL);
                self.ws.binaryType = 'arraybuffer';

                self.ws.onmessage = function (event) {
                    var result = JSON.parse(event.data);
                    if (result.partial && self.onPartial) {
                        self.onPartial(result.partial);
                    }
                    if (result.text && self.onPartial) {
                        self.onPartial(result.text);
                    }
                };

                self.ws.onerror = function () {
                    self._cleanup();
                    if (self.onError) self.onError(new Error('Vosk-сервер недоступен'));
                    reject(new Error('Vosk-сервер недоступен'));
                };

                self.ws.onclose = function () {
                    if (self.recording) {
                        self._cleanup();
                        reject(new Error('Соединение с Vosk разорвано'));
                    }
                };

                self.ws.onopen = function () {
                    navigator.mediaDevices.getUserMedia({
                        audio: {
                            echoCancellation: true,
                            noiseSuppression: true,
                            channelCount: 1,
                            sampleRate: SAMPLE_RATE
                        }
                    }).then(function (stream) {
                        self.stream = stream;
                        self.context = new AudioContext({ sampleRate: SAMPLE_RATE });

                        return self.context.audioWorklet.addModule(WORKLET_URL).then(function () {
                            self.source = self.context.createMediaStreamSource(stream);
                            self.workletNode = new AudioWorkletNode(self.context, 'float32-to-int16-processor');

                            self.workletNode.port.onmessage = function (e) {
                                if (!self.recording || self.ws.readyState !== WebSocket.OPEN) return;
                                var float32 = e.data.audio;
                                var int16 = new Int16Array(float32.length);
                                for (var i = 0; i < float32.length; i++) {
                                    var s = Math.max(-1, Math.min(1, float32[i]));
                                    int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
                                }
                                self.ws.send(int16.buffer);
                            };

                            self.source.connect(self.workletNode);
                            self.workletNode.connect(self.context.destination);
                            self.recording = true;
                            resolve();
                        });
                    }).catch(function (err) {
                        self._cleanup();
                        if (self.onError) self.onError(err);
                        reject(err);
                    });
                };
            } catch (err) {
                self._cleanup();
                if (self.onError) self.onError(err);
                reject(err);
            }
        });
    };

    VoiceRecorder.prototype.stop = function () {
        var self = this;
        if (!self.recording) return Promise.resolve('');

        return new Promise(function (resolve, reject) {
            self._resolve = resolve;
            self._reject = reject;
            self.recording = false;

            if (self.workletNode) {
                self.workletNode.port.postMessage('flush');
            }

            if (self.ws && self.ws.readyState === WebSocket.OPEN) {
                self.ws.send(JSON.stringify({ eof: 1 }));

                var timeout = setTimeout(function () {
                    self._cleanup();
                    resolve('');
                }, 2000);

                var origOnMessage = self.ws.onmessage;
                self.ws.onmessage = function (event) {
                    clearTimeout(timeout);
                    var result = JSON.parse(event.data);
                    var text = result.text || '';
                    self._cleanup();
                    resolve(text);
                };
            } else {
                self._cleanup();
                resolve('');
            }
        });
    };

    VoiceRecorder.prototype._cleanup = function () {
        this.recording = false;
        if (this.workletNode) {
            this.workletNode.disconnect();
            this.workletNode = null;
        }
        if (this.source) {
            this.source.disconnect();
            this.source = null;
        }
        if (this.context) {
            this.context.close().catch(function () {});
            this.context = null;
        }
        if (this.stream) {
            this.stream.getTracks().forEach(function (t) { t.stop(); });
            this.stream = null;
        }
        if (this.ws) {
            this.ws.onmessage = null;
            this.ws.onerror = null;
            this.ws.onclose = null;
            if (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING) {
                this.ws.close();
            }
            this.ws = null;
        }
    };

    window.VoiceRecorder = VoiceRecorder;
})();
