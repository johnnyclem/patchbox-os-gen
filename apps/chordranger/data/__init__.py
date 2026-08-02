"""Factory content: the styles and chordsets baked into the image.

Kept as Python rather than JSON on the data partition because a unit whose
card has been wiped — or a fresh build under CI — still has to boot playable.
The user's own content lives beside it under ``[paths] data_dir`` and always
wins where the names collide.
"""
