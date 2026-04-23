/* Alpine component for the PDF upload modal.
 * Responsibility: validate + upload the file, then redirect to the deck page.
 * The deck page handles all "generating" state and polling — the modal no
 * longer needs to wait for card generation to finish.
 */
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
      this.pct = 20;
      this.stage = 'Uploading PDF';
      this.stageDetail = 'Sending file to the server…';

      try {
        const fd = new FormData();
        fd.append('file', this.file);
        if (this.name) fd.append('name', this.name);

        const res = await fetch('/api/decks/upload', { method: 'POST', body: fd });
        if (res.status === 401) { window.location.href = '/login'; return; }
        if (!res.ok) {
          let msg = `Upload failed (${res.status})`;
          try { const j = await res.json(); if (j.detail) msg = j.detail; } catch {}
          throw new Error(msg);
        }

        const deck = await res.json();
        this.pct = 100;
        this.stage = 'Upload complete';
        this.stageDetail = 'Opening your deck…';

        // Redirect immediately — the deck page handles generation polling.
        setTimeout(() => { window.location.href = `/decks/${deck.id}`; }, 600);

      } catch (e) {
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
    },
  };
}
