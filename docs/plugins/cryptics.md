# Cryptic Crossword Plugin

command phrase: "crossword, please"

This is going to be fairly simple so we can test the concept. As such, no
dealing with accounts or paywalls or whatever. We can just use the
[Hex](https://coxrathvon.com/) archive. Pick a link at random; complete random
because even if I have done it before (and I have done a bunch of them) they're
usually hard enough I don't remember the answers. So:

- random link
- add `/pdf` to the link
- request and follow the redirect
- print the PDF

Plugin now does the same for multiple cryptic sites, Hex and Mad Dog. Adding
additional sites is just a matter of a URL and a way to extract printable
puzzles.
