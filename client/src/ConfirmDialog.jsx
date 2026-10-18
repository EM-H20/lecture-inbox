import React, { useEffect, useRef } from 'react';
import './confirm.css';

// A modal second ask before deleting; Escape and 취소 cancel unless the deletion is already running.
export default function ConfirmDialog({ title, children, busy, onConfirm, onCancel }) {
  const dialog = useRef(null);
  useEffect(() => { dialog.current?.showModal(); }, []);
  return <dialog className="confirm-dialog" ref={dialog} aria-labelledby="confirm-title"
    onCancel={(event) => { event.preventDefault(); if (!busy) onCancel(); }}>
    <h3 id="confirm-title">{title}</h3>
    <p>{children}</p>
    <div className="confirm-actions">
      <button className="secondary" autoFocus disabled={busy} onClick={onCancel}>취소</button>
      <button className="primary danger" disabled={busy} onClick={onConfirm}>{busy ? '삭제하는 중…' : '삭제'}</button>
    </div>
  </dialog>;
}
