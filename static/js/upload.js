/* Alpine component for the PDF upload modal. */
function uploadModal() {
  return {
    open: false,
    file: null,
    name: '',
    dragOver: false,
    busy: false,
    error: '',
    pct: 0,
    stage: 'Uploading PDF',
    stageDetail: 'Sending file to the server',
    _pollTimer: null,

    handlePick(ev) {
      const f = ev.target.files && ev.target.files[0];
      if (f) this.setFile(f);
    },
    handleDrop(ev) {
      this.dragOver = false;
      const f = ev.dataTransfer.files && ev.dataTransfer.files[0];
      if (f) this.setFile(f);
    },
    setFile(f) {
      if (f.type !== 'application/pdf' && !f.name.toLowerCase().endsWith('.pdf')) {
        this.error = 'That file does not look like a PDF.';
        return;
      }
      if (f.size > 10 * 1024 * 1024) {
        this.error = 'PDF exceeds the 10 MB limit.';
        return;
      }
      this.file = f;
      this.error = '';
      if (!this.name) {
        this.name = f.name.replace(/\.pdf$/i, '').replace(/[_-]+/g, ' ').trim();
      }
    },

    async submit() {
      if (!this.file) return;
      this.busy = true;
      this.error = '';
      this.pct = 5;
      this.stage = 'Uploading PDF';
      this.stageDetail = 'Sending file to the server';

      try {
        const fd = new FormData();
        fd.append('file', this.file);
        if (this.name) fd.append('name', this.name);

        // Step 1: Upload (returns instantly with deck in "processing" state).
        const res = await fetch('/api/decks/upload', { method: 'POST', body: fd });
        if (res.status === 401) {
          window.location.href = '/login';
          return;
        }
        if (!res.ok) {
          let msg = `Upload failed (${res.status})`;
          try { const j = await res.json(); if (j.detail) msg = j.detail; } catch {}
          throw new Error(msg);
        }
        const deck = await res.json();
        this.pct = 15;
        this.stage = 'Generating flashcards';
        this.stageDetail = 'AI is reading your document and writing cards…';

        // Step 2: Poll /status until generation is done.
        await this._pollUntilReady(deck.id);

      } catch (e) {
        this._stopPoll();
        this.busy = false;
        this.error = e.message || 'Something went wrong.';
      }
    },

    _pollUntilReady(deckId) {
      return new Promise((resolve, reject) => {
        let tick = 0;
        this._pollTimer = setInterval(async () => {
          tick++;
          try {
            const res = await fetch(`/api/decks/${deckId}/status`);
            if (!res.ok) {
              // transient — keep trying for a while
              if (tick > 90) { // 90 × 2s = 3 min
                throw new Error('Generation is taking too long. Please try a smaller PDF.');
              }
              return;
            }
            const data = await res.json();

            if (data.generation_status === 'ready') {
              this._stopPoll();
              this.pct = 100;
              this.stage = 'Done';
              const total = data.stats?.total ?? 0;
              this.stageDetail = `Generated ${total} cards`;
              // Wait until the card count is non-zero before redirecting.
              // The backend commits cards first then flips status, so cards
              // should already be visible — but give it one extra poll to be sure.
              if (total === 0) {
                // Re-poll once more in 1.5 s to get the real count, then redirect.
                setTimeout(async () => {
                  try {
                    const r2 = await fetch(`/api/decks/${deckId}/status`);
                    if (r2.ok) {
                      const d2 = await r2.json();
                      const realTotal = d2.stats?.total ?? 0;
                      this.stageDetail = `Generated ${realTotal} cards`;
                    }
                  } finally {
                    window.location.href = `/decks/${deckId}`;
                  }
                }, 1500);
              } else {
                setTimeout(() => { window.location.href = `/decks/${deckId}`; }, 800);
              }
              resolve();
            } else if (data.generation_status === 'failed') {
              this._stopPoll();
              throw new Error(data.generation_error || 'Card generation failed.');
            } else {
              // Still processing — animate progress.
              // Ease toward 90% asymptotically so it never stalls visually.
              const target = 15 + Math.min(75, tick * 2.5);
              this.pct = Math.min(92, this.pct + (target - this.pct) * 0.15);

              if (this.pct < 40) {
                this.stage = 'Reading PDF';
                this.stageDetail = 'Extracting and chunking text';
              } else if (this.pct < 80) {
                this.stage = 'Writing flashcards';
                this.stageDetail = 'AI is drafting questions and answers';
              } else {
                this.stage = 'Finishing up';
                this.stageDetail = 'Saving cards to your deck';
              }
            }
          } catch (e) {
            this._stopPoll();
            this.busy = false;
            this.error = e.message || 'Something went wrong.';
            reject(e);
          }
        }, 2000);
      });
    },

    _stopPoll() {
      if (this._pollTimer) {
        clearInterval(this._pollTimer);
        this._pollTimer = null;
      }
    },

    reset() {
      this.file = null;
      this.name = '';
      this.busy = false;
      this.error = '';
      this.pct = 0;
      this._stopPoll();
    },
  };
}
