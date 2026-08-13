# Why this hotfix exists

The A/B forward research data is present even when there are no trades, but the browser can still show an empty lab when legacy rendering code overwrites the shared lab container. The dedicated A/B renderer must own the lab view and restore it if that happens.
