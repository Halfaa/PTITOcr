# Medical document corpus — subset

25 images across 5 sets, with their ground truth.

Drawn from a full corpus of 699 images. Handwriting only. Degradation sets are reduced to the levels cited in the documents, on a single page, so that the archive stays mailable; the full sets are regenerated with scripts/degrader.py.

| set | what is included |
|---|---|
| `handwriting_en` | 3 pages |
| `handwriting_en_degradation` | 8 images = 1 page x 8 paliers cites |
| `handwriting_vi` | 3 pages |
| `handwriting_vi_degradation` | 8 images = 1 page x 8 paliers cites |
| `handwriting_vi_warped` | 3 pages |

## Layout

```
       handwriting/<set>/   handwritten forms, VN and EN
manifest.json               one entry per image
```

## Ground truth

**Handwriting** — one `*_verite.json` per image, right next to it, holding the exact value of every handwritten field (and, for English, the handwriting font used). Degraded and warped pages keep the truth of their source specimen: the degradation only touches pixels.

## Caveats

Every synthetic set is generated: LaTeX for the content, Blender for warping and lighting, handwriting fonts for the script. That is what makes the ground truth exact — and it is also the main limitation. Vietnamese handwriting uses a single font, English uses seven.
