"""Model-specific prompt and stopping contracts for installed local translators."""
def prompt(tokenizer, name, text, direction, topic='none', context=(), pairs=()):
    """`pairs`: (source, translation) of the sentences right before `text`. They open both
    sides of the prompt, so the model continues its own translation of them with `text`."""
    if name != 'milmmt':raise ValueError('Only the MiLMMT translation contract is supported')
    from .languages import prompt_names
    source,target = prompt_names(direction)
    content=f'Translate this from {source} to {target}:\n{source}: {text}\n{target}:'
    if pairs:
        before=' '.join(item[0] for item in pairs);done=' '.join(item[1] for item in pairs)
        content=f'Translate this from {source} to {target}:\n{source}: {before} {text}\n{target}: {done}'
    if context:
        content='Background from preceding speech (do not translate or repeat):\n'+'\n'.join(context)+'\nTranslate only the new continuation below.\n'+content
    return tokenizer.encode(content,add_special_tokens=False)

def configure(tokenizer,name):
    if name!='milmmt':raise ValueError('Only the MiLMMT translation contract is supported')
    tokenizer.eos_token_ids={1,106}
