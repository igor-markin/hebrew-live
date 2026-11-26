/** Parts of the window the owner can hide: the menu bar and the session list. The choice is saved
 * with the other preferences, because the window's address (and so its localStorage) changes every
 * launch; localStorage only shows it before the first state arrives. */
export const MENU_HIDDEN_KEY='hebrew-live-menu-hidden';
export const SESSIONS_HIDDEN_KEY='hebrew-live-sessions-hidden';

/** A stored flag: only «1» hides; anything else, or nothing, shows the part. */
export function storedHidden(value:string|null|undefined):boolean{
  return value==='1';
}

export function storedValue(hidden:boolean):string{
  return hidden?'1':'0';
}
