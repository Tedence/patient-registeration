// localStorage-backed session drafts.
// Key shape: `session_draft_{draftId}`. Value: the full draft JSON.
// Drafts survive tab close; purged on successful End Session upload.

const PREFIX = "session_draft_";

export function draftKey(draftId) {
  return `${PREFIX}${draftId}`;
}

export function saveDraft(draft) {
  localStorage.setItem(draftKey(draft.draftId), JSON.stringify(draft));
}

export function loadDraft(draftId) {
  const raw = localStorage.getItem(draftKey(draftId));
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function discardDraft(draftId) {
  localStorage.removeItem(draftKey(draftId));
}

export function listDraftsForPatient(patientLabel) {
  const out = [];
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (!key || !key.startsWith(PREFIX)) continue;
    try {
      const draft = JSON.parse(localStorage.getItem(key));
      if (draft?.patient_label === patientLabel) out.push(draft);
    } catch {
      // ignore corrupt draft blobs
    }
  }
  out.sort(
    (a, b) =>
      new Date(b.started_at_utc).getTime() - new Date(a.started_at_utc).getTime()
  );
  return out;
}

export function newDraftId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `d_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}
