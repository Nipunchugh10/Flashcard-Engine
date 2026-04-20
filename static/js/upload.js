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
    stage: 'Reading PDF',
    stageDetail: 'Extracting text from your document',
    _progressTimer: null,

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
      if (f.size > 25 * 1024 * 1024) {
        this.error = 'PDF exceeds the 25 MB limit.';
        return;
      }
      this.file = f;
      this.error = '';
      if (!this.name) {
        this.name = f.name.replace(/\.pdf$/i, '').replace(/[_-]+/g, ' ').trim();
      }
    },

    _tickProgress() {
      // The backend is a single synchronous call (extract + LLM).
      // We show staged fake progress so the user isn't staring at a blank bar.
      // Pct eases toward a ceiling it will never reach until the real response lands.
      const stages = [
        { until: 15, label: 'Reading PDF',       detail: 'Extracting text from your document' },
        { until: 45, label: 'Chunking content',  detail: 'Splitting into digestible sections' },
        { until: 92, label: 'Writing flashcards',detail: 'Drafting questions and answers' },
      ];
      this._progressTimer = setInterval(() => {
        // jitter so it feels alive
        const step = 0.6 + Math.random() * 1.4;
        // asymptotic approach to 92
        if (this.pct < 92) this.pct = Math.min(92, this.pct + step);
        for (const s of stages) {
          if (this.pct <= s.until) {
            this.stage = s.label;
            this.stageDetail = s.detail;
            break;
          }
        }
      }, 350);
    },

    async submit() {
      if (!this.file) return;
      this.busy = true;
      this.error = '';
      this.pct = 2;
      this._tickProgress();

      try {
        const fd = new FormData();
        fd.append('file', this.file);
        if (this.name) fd.append('name', this.name);

        const res = await fetch('/api/decks/upload', { method: 'POST', body: fd });

        clearInterval(this._progressTimer);
        if (!res.ok) {
          let msg = `Upload failed (${res.status})`;
          try { const j = await res.json(); if (j.detail) msg = j.detail; } catch {}
          throw new Error(msg);
        }
        const deck = await res.json();
        this.pct = 100;
        this.stage = 'Done';
        this.stageDetail = `Generated ${deck.stats?.total ?? 0} cards`;
        setTimeout(() => { window.location.href = `/decks/${deck.id}`; }, 400);
      } catch (e) {
        clearInterval(this._progressTimer);
        this.busy = false;
        this.error = e.message || 'Something went wrong.';
      }
    },

    reset() {
      this.file = null;
      this.name = '';
      this.busy = false;
      this.error = '';
      this.pct = 0;
      clearInterval(this._progressTimer);
    },
  };
}
