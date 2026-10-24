import React, { useEffect, useState } from "react";
import { kindlePreview, saveKindleSettings, sendToKindle } from "../api";

// Outgoing mail servers of the common providers, so a reader types only
// their address and an app password; anything else goes under "Gelişmiş".
const PROVIDERS = [
  { domains: ["gmail.com", "googlemail.com"], host: "smtp.gmail.com", port: 587,
    help: "https://myaccount.google.com/apppasswords" },
  { domains: ["outlook.com", "hotmail.com", "live.com", "msn.com"], host: "smtp-mail.outlook.com", port: 587 },
  { domains: ["icloud.com", "me.com", "mac.com"], host: "smtp.mail.me.com", port: 587 },
  { domains: ["yahoo.com"], host: "smtp.mail.yahoo.com", port: 465 },
  { domains: ["yandex.com", "yandex.com.tr", "yandex.ru"], host: "smtp.yandex.com", port: 465 },
];

function providerFor(email) {
  const domain = (email.split("@")[1] || "").trim().toLowerCase();
  return PROVIDERS.find((p) => p.domains.includes(domain)) || null;
}

// Send to Kindle (backend/app/kindle_send.py): set up once, then every send
// shows what goes where and waits for "Gönder". The EPUB is checked first;
// one that fails its check is never sent.
export default function SendToKindleModal({ sessionId, onClose, onBeforeSend }) {
  const [preview, setPreview] = useState(null);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(null);
  const [advanced, setAdvanced] = useState(false);
  const [form, setForm] = useState({
    kindle_email: "", from_email: "", smtp_host: "", smtp_port: 587, smtp_user: "", smtp_password: "",
  });
  const provider = providerFor(form.from_email);
  // what is actually saved: the provider's server and the sender address as
  // the login, unless the reader filled those in themselves
  const settings = {
    ...form,
    smtp_host: form.smtp_host || provider?.host || "",
    smtp_port: form.smtp_host ? form.smtp_port : provider?.port || form.smtp_port,
    smtp_user: form.smtp_user || form.from_email,
  };

  const load = async () => {
    setError(null);
    try {
      await onBeforeSend?.();
      const p = await kindlePreview(sessionId);
      setPreview(p);
      setEditing(!p.configured);
    } catch (e) {
      setError(e.message);
    }
  };

  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await saveKindleSettings(settings);
      setForm((f) => ({ ...f, smtp_password: "" }));
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      setDone(await sendToKindle(sessionId));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const field = (key, label, type = "text", placeholder = "") => (
    <label className="modal-field">
      {label}
      <input
        type={type}
        value={form[key]}
        placeholder={placeholder}
        onChange={(e) => setForm({ ...form, [key]: e.target.value })}
      />
    </label>
  );

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-panel" role="dialog" aria-label="Kindle'a gönder" onClick={(e) => e.stopPropagation()}>
        <h2>Kindle'a gönder</h2>

        {!preview && !error && <p className="modal-panel__hint">EPUB hazırlanıyor ve doğrulanıyor…</p>}

        {preview && editing && (
          <>
            <p className="modal-panel__hint">
              Matbaa kitabı sizin e-posta hesabınızdan Kindle adresinize ek olarak yollar; Amazon da onu
              kitaplığınıza koyar. Bir kez ayarlanır, yalnız bu bilgisayarda saklanır.
            </p>
            {field("kindle_email", "Kindle e-posta adresi (Amazon › Cihazlar › Kindle'ınız)", "email", "adiniz@kindle.com")}
            {field("from_email", "Kendi e-posta adresiniz (Amazon'da onaylı olmalı)", "email", "siz@gmail.com")}
            {field("smtp_password", "Uygulama şifresi (e-posta şifreniz değil)", "password")}
            {provider?.help && (
              <p className="modal-panel__hint">
                Gmail uygulama şifresi:{" "}
                <a href={provider.help} target="_blank" rel="noreferrer">myaccount.google.com/apppasswords</a>{" "}
                adresinde “Matbaa” adıyla oluşturun, verilen 16 harfi buraya yapıştırın (iki adımlı doğrulama açık
                olmalı).
              </p>
            )}
            {form.from_email.includes("@") && !provider && !advanced && (
              <p className="modal-panel__hint">Bu e-posta sağlayıcısını tanımıyorum; “Gelişmiş” altından sunucuyu girin.</p>
            )}
            <button type="button" className="modal-link" onClick={() => setAdvanced(!advanced)}>
              {advanced ? "Gelişmiş ayarları gizle" : "Gelişmiş (SMTP sunucusu)"}
            </button>
            {advanced && (
              <>
                {field("smtp_host", "SMTP sunucusu", "text", provider?.host || "smtp.ornek.com")}
                {field("smtp_port", "SMTP portu", "number")}
                {field("smtp_user", "SMTP kullanıcı adı", "text", form.from_email)}
              </>
            )}
            <div className="modal-actions">
              <button onClick={onClose}>İptal</button>
              {preview.configured && <button onClick={() => setEditing(false)}>Geri</button>}
              <button
                className="btn btn--primary"
                onClick={save}
                disabled={busy || !settings.kindle_email || !settings.smtp_host || !settings.smtp_user
                          || !settings.smtp_password}
              >
                Kaydet
              </button>
            </div>
          </>
        )}

        {preview && !editing && !done && (
          <>
            <p className="modal-panel__hint">
              “{preview.title}” ({preview.filename}, {preview.size_mb} MB) <strong>{preview.kindle_email}</strong>{" "}
              adresine, {preview.from_email} adresinden gönderilecek.
            </p>
            {preview.warning && (
              <p className="modal-panel__error">Ayarlarda bir sorun var: {preview.warning} “Ayarları değiştir”den düzeltin.</p>
            )}
            {!preview.valid && (
              <p className="modal-panel__error">
                EPUB doğrulamadan geçmedi, gönderilemez: {preview.errors.join("; ")}
              </p>
            )}
            {preview.size_mb > preview.limit_mb && (
              <p className="modal-panel__error">
                Dosya e-posta sınırını ({preview.limit_mb} MB) aşıyor; Amazon'un web yükleyicisini kullanın.
              </p>
            )}
            <div className="modal-actions">
              <button onClick={onClose}>Vazgeç</button>
              <button onClick={() => setEditing(true)}>Ayarları değiştir</button>
              <button
                className="btn btn--primary"
                onClick={send}
                disabled={busy || !preview.valid || preview.size_mb > preview.limit_mb}
              >
                {busy ? "Gönderiliyor…" : "Gönder"}
              </button>
            </div>
          </>
        )}

        {done && (
          <>
            <p className="modal-panel__preview">
              Gönderildi: {done.to} ({done.size_mb} MB). Kitap birkaç dakika içinde Kindle'ınızda görünür.
            </p>
            <div className="modal-actions">
              <button className="btn btn--primary" onClick={onClose}>Tamam</button>
            </div>
          </>
        )}

        {error && <p className="modal-panel__error">{error}</p>}
      </div>
    </div>
  );
}
