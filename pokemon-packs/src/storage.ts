// Ochrana sbírky: trvalé úložiště a připomínka zálohy.
//
// Prohlížeč při nedostatku místa maže data webů vcelku, tedy i sbírku
// v localStorage. Trvalé úložiště (navigator.storage.persist) tomu brání;
// Chrome ho povolí sám (typicky nainstalované aplikaci), Firefox se zeptá.

const BACKUP_KEY = "pokemon-packs:last-backup";
const REMIND_AFTER = 30 * 24 * 60 * 60 * 1000;

export async function isPersisted(): Promise<boolean> {
  try {
    return (await navigator.storage?.persisted?.()) ?? false;
  } catch {
    return false;
  }
}

/** Požádá o trvalé úložiště; vrací, zda ho web má. */
export async function persistStorage(): Promise<boolean> {
  try {
    if (await isPersisted()) return true;
    return (await navigator.storage?.persist?.()) ?? false;
  } catch {
    return false;
  }
}

export function lastBackup(): number | null {
  try {
    const at = Number(localStorage.getItem(BACKUP_KEY));
    return at > 0 ? at : null;
  } catch {
    return null;
  }
}

export function markBackup() {
  try {
    localStorage.setItem(BACKUP_KEY, String(Date.now()));
  } catch {
    // nevadí
  }
}

/** Připomenout zálohu: úložiště není trvalé a poslední záloha je stará nebo žádná. */
export async function shouldRemindBackup(): Promise<boolean> {
  if (await isPersisted()) return false;
  const at = lastBackup();
  return at === null || Date.now() - at > REMIND_AFTER;
}
