(function () {
    function TTSPlayer() {
        this.audio = new Audio();
        this.enabled = true;
        this.playing = false;
        this._url = null;
        this.onStateChange = null;
        this._unlocked = false;
        this._pendingBlob = null;

        var self = this;
        this.audio.addEventListener('ended', function () {
            self.playing = false;
            self._revokeUrl();
            if (self.onStateChange) self.onStateChange('stopped');
        });
        this.audio.addEventListener('error', function () {
            self.playing = false;
            self._revokeUrl();
            if (self.onStateChange) self.onStateChange('error');
        });

        var unlock = function () {
            if (self._unlocked) return;
            self._unlocked = true;
            var silent = new Audio('data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=');
            silent.play().then(function () {
                if (self._pendingBlob) {
                    self._playBlob(self._pendingBlob);
                    self._pendingBlob = null;
                }
            }).catch(function () {});
            document.removeEventListener('click', unlock);
            document.removeEventListener('keydown', unlock);
        };
        document.addEventListener('click', unlock);
        document.addEventListener('keydown', unlock);
    }

    TTSPlayer.prototype._playBlob = function (blob) {
        var self = this;
        self._revokeUrl();
        self._url = URL.createObjectURL(blob);
        self.audio.src = self._url;
        self.playing = true;
        if (self.onStateChange) self.onStateChange('playing');
        self.audio.play().catch(function () {
            self.playing = false;
            if (self.onStateChange) self.onStateChange('error');
        });
    };

    TTSPlayer.prototype.speak = function (text) {
        if (!this.enabled || !text) return;
        this.stop();

        var self = this;
        if (self.onStateChange) self.onStateChange('loading');

        fetch('/api/tts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: text })
        })
        .then(function (resp) {
            if (!resp.ok) throw new Error('TTS request failed');
            return resp.blob();
        })
        .then(function (blob) {
            if (self._unlocked) {
                self._playBlob(blob);
            } else {
                self._pendingBlob = blob;
                if (self.onStateChange) self.onStateChange('waiting');
            }
        })
        .catch(function () {
            self.playing = false;
            self._revokeUrl();
            if (self.onStateChange) self.onStateChange('error');
        });
    };

    TTSPlayer.prototype.stop = function () {
        if (!this.playing) return;
        this.audio.pause();
        this.audio.currentTime = 0;
        this.playing = false;
        this._revokeUrl();
        if (this.onStateChange) this.onStateChange('stopped');
    };

    TTSPlayer.prototype.toggle = function () {
        this.enabled = !this.enabled;
        if (!this.enabled) this.stop();
        return this.enabled;
    };

    TTSPlayer.prototype._revokeUrl = function () {
        if (this._url) {
            URL.revokeObjectURL(this._url);
            this._url = null;
        }
    };

    window.TTSPlayer = TTSPlayer;
})();
