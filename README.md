# Daihesi Dictionary

A dictionary and translator for the Daihesi language of Daihesilend.

https://jmatt266.github.io/Daihesi-Dictionary/

## Rebuild the site

`index.html` is generated. Edit `src/template.html`, then from the repository root run:

```
python3 src/build.py -o index.html
```

The builder reads `src/doc-export.json`, capitalizes lexicon headwords, and embeds `src/assets/logo.png` (the Hakelimebel) and `src/assets/favicon.png`. The same emblem is kept at `src/hakelimebel-gold.png`.
