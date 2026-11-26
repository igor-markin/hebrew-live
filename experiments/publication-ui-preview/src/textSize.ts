/** Size of the conversation text (Hebrew, translation, history), chosen in the settings and kept
 * in this browser like the theme. Controls and headings keep their size. */
export const TEXT_SIZES=['smallest','small','normal','large'] as const;
export type TextSize=typeof TEXT_SIZES[number];
export const TEXT_SIZE_KEY='hebrew-live-text-size';
/** Multiplier of the reading sizes; «normal» is the earlier fixed size (translation 20 px). */
export const TEXT_SCALE:Record<TextSize,number>={smallest:.8,small:.9,normal:1,large:1.15};

export function textSize(value:string|null|undefined):TextSize{
  return (TEXT_SIZES as readonly string[]).includes(value||'')?value as TextSize:'normal';
}

/** Translation size in px at a size, for the option labels. */
export function translationPixels(size:TextSize):number{
  return Math.round(20*TEXT_SCALE[size]);
}
