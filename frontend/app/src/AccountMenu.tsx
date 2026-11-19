// Optional visitor account (EVE SSO). Hidden unless the server has the login configured. Signing in always goes
// through a consent dialog listing exactly what is read and kept; the session itself is an HttpOnly cookie, so
// nothing secret ever reaches this code.
import { useEffect, useState } from "react";
import type { MessageKey, TFunction } from "./i18n";
import { ProfilePanel } from "./ProfilePanel";

interface AuthStatus {
  enabled: boolean;
  authenticated: boolean;
  needs_consent?: boolean;
  consent_version: string;
  character: { id: number; name: string } | null;
}

const NOTICES: Record<string, MessageKey> = {
  ok: "account.notice.ok", denied: "account.notice.denied", error: "account.notice.error",
};

async function loadStatus(): Promise<AuthStatus | null> {
  try {
    const response = await fetch("/api/auth/status", { cache: "no-store" });
    return response.ok ? ((await response.json()) as AuthStatus) : null;
  } catch {
    return null;
  }
}

export function AccountMenu({ t }: { t: TFunction }) {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [dialog, setDialog] = useState(false);
  const [menu, setMenu] = useState(false);
  const [profile, setProfile] = useState(false);
  const [notice, setNotice] = useState<MessageKey | null>(null);

  useEffect(() => {
    void loadStatus().then(setStatus);
    const flag = new URLSearchParams(window.location.search).get("login");
    if (flag && NOTICES[flag]) {
      setNotice(NOTICES[flag]);
      const url = new URL(window.location.href);
      url.searchParams.delete("login");
      window.history.replaceState(null, "", url.pathname + url.search + url.hash);
    }
  }, []);

  useEffect(() => {
    if (!dialog) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setDialog(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [dialog]);

  if (!status?.enabled) return null;
  const signedIn = status.authenticated && !status.needs_consent;

  async function signOut() {
    await fetch("/api/auth/logout", { method: "POST" });
    setMenu(false);
    setStatus(await loadStatus());
  }

  async function exportData() {
    const response = await fetch("/api/auth/me/export", { cache: "no-store" });
    if (!response.ok) return;
    const blob = new Blob([JSON.stringify(await response.json(), null, 2)], { type: "application/json" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "evemarket-my-data.json";
    link.click();
    URL.revokeObjectURL(link.href);
  }

  async function deleteData() {
    if (!window.confirm(t("account.deleteConfirm"))) return;
    await fetch("/api/auth/me", { method: "DELETE" });
    setMenu(false);
    setStatus(await loadStatus());
  }

  return (
    <>
      {signedIn && status.character ? (
        <div className="account">
          <button className="account-btn" aria-expanded={menu} aria-label={t("account.menu")} onClick={() => setMenu(!menu)}>
            {status.character.name}
          </button>
          {menu && (
            <div className="account-menu" role="menu">
              <button role="menuitem" onClick={() => { setMenu(false); setProfile(true); }}>{t("profile.open")}</button>
              <button role="menuitem" onClick={() => void exportData()}>{t("account.export")}</button>
              <button role="menuitem" onClick={() => void signOut()}>{t("account.signOut")}</button>
              <button role="menuitem" className="danger" onClick={() => void deleteData()}>{t("account.delete")}</button>
            </div>
          )}
        </div>
      ) : (
        <button className="account-btn" onClick={() => setDialog(true)}>{t("account.signIn")}</button>
      )}

      {profile && signedIn && <ProfilePanel t={t} onClose={() => setProfile(false)} />}

      {notice && (
        <div className="account-notice" role="status" onClick={() => setNotice(null)}>{t(notice)}</div>
      )}

      {dialog && (
        <div className="modal-backdrop" onClick={() => setDialog(false)}>
          <div className="modal" role="dialog" aria-modal="true" aria-labelledby="consent-title" onClick={(e) => e.stopPropagation()}>
            <h2 id="consent-title">{t("account.consentTitle")}</h2>
            <p>{t("account.consentIntro")}</p>
            <ul>
              <li>{t("account.consentData")}</li>
              <li>{t("account.consentKept")}</li>
              <li>{t("account.consentNever")}</li>
              <li>{t("account.consentRights")}</li>
            </ul>
            <p><a href="/privacy" target="_blank" rel="noopener">{t("account.consentPolicy")}</a></p>
            <div className="modal-actions">
              <button className="account-btn" onClick={() => setDialog(false)}>{t("account.consentCancel")}</button>
              <a className="account-btn primary"
                href={`/api/auth/login?consent=${encodeURIComponent(status.consent_version)}`}>
                {t("account.consentContinue")}
              </a>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
