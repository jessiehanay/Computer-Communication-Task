# Multi-Threaded Web Server — Computer Networks Assignment

**Students:**
- Jessie Hanay — 341112381
- Tehilla Schamroth — 214918914

**Demo video:** https://www.loom.com/share/f4a71055c38541769ebb7426928c7426

**About the Assignment:**

This project is a multi-threaded HTTP/1.0 web server written from scratch in
Python, using only the low-level socket API — no web frameworks. The server
manually manages TCP connections (bind, listen, accept), reads and parses raw
HTTP request bytes, serves static files (HTML, CSS, SVG) over GET, and returns
correct HTTP status codes.
