## Bored Girl Bass

I thought I'd test out the new built-in oscillators in DecentSampler and oh boy:
* Certain knob bindings are still undocumented as of this commit
* I cannot figure out what's going on with the effects chain. WAV files will go through global effects,
  but oscillators only go through specific global ones and not filter or reverb? You can attach the
  fx to groups and busses and then they work but it gets complicated and you can't just use one paradigm.
  I suspect this is a bug?

Anyway, I've stalled on this for now. I need to document observations when I'm not half asleep.
