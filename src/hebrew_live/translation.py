"""Model-specific prompt and stopping contracts for installed local translators."""
def prompt(tokenizer, name, text, direction, topic='none', context=()):
    if name != 'milmmt':raise ValueError('Only the MiLMMT translation contract is supported')
    from .languages import prompt_names
    source,target = prompt_names(direction)
    pairs=[item for item in context if isinstance(item,(tuple,list))]
    if pairs:
        # Already shown (source, translation) pairs: the source joins the text and the
        # translation is forced as the start of the answer, so the model writes only the
        # continuation and cannot repeat or reword what is on screen.
        text=' '.join([*(pair[0] for pair in pairs),text])
        context=[item for item in context if not isinstance(item,(tuple,list))]
    content=f'Translate this from {source} to {target}:\n{source}: {text}\n{target}:'
    if context:
        content='Background from preceding speech (do not translate or repeat):\n'+'\n'.join(context)+'\nTranslate only the new continuation below.\n'+content
    if pairs:content+=' '+' '.join(pair[1] for pair in pairs)
    return tokenizer.encode(content,add_special_tokens=False)

def configure(tokenizer,name):
    if name!='milmmt':raise ValueError('Only the MiLMMT translation contract is supported')
    tokenizer.eos_token_ids={1,106}
