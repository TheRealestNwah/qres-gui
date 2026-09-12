# Third-party notices

QRes GUI itself is MIT-licensed (see `LICENSE`). The Windows download also
contains the third-party software below. Full license texts are in the
`licenses` folder of the download (and of the source repository).

QRes.exe (by Anders Kjersem) is **not** included; it's a separate program with
its own terms.

| Component | Version | License | Text |
|---|---|---|---|
| Qt (Qt Core, Qt GUI, Qt Widgets, platform / style / image-format plugins) | 6.11.2 | LGPL-3.0-only | `LGPL-3.0.txt`, `GPL-3.0.txt` |
| PySide6 and Shiboken6 (Qt for Python) | 6.11.2 | LGPL-3.0-only (of LGPL-3.0-only / GPL-2.0-only / GPL-3.0-only) | `LGPL-3.0.txt`, `GPL-3.0.txt` |
| Python | 3.13 | PSF License Agreement | `Python-LICENSE.txt` |
| OpenSSL (libcrypto, libssl) | 3.x | Apache-2.0 | `Python-LICENSE.txt` |
| libffi | 3.x | MIT | `Python-LICENSE.txt` |
| bzip2 / libbzip2 | 1.0.8 | bzip2 license (BSD-style) | `Python-LICENSE.txt` |
| Microsoft Visual C++ runtime and Universal CRT | — | Microsoft Distributable Code | `Python-LICENSE.txt` ("Additional Conditions") |
| psutil | 7.2.2 | BSD-3-Clause | `psutil-LICENSE.txt` |
| PyInstaller bootloader | 6.22.2 | GPL-2.0-or-later with the PyInstaller Bootloader Exception | `PyInstaller-COPYING.txt` |
| Expat (XML parser in Python) | 2.x | MIT | below |
| mpdecimal (decimal arithmetic in Python) | 2.5 | BSD-2-Clause | below |
| SQLite | 3.x | Public domain | — |
| XZ Utils (liblzma) | 5.x | Public domain / 0BSD | — |
| zlib | 1.3 | zlib license (no notice required in binaries) | — |

## Qt and PySide6 (LGPL-3.0)

QRes GUI uses Qt and PySide6 under the GNU Lesser General Public License v3,
as unmodified dynamically linked libraries: the Qt and PySide6 DLLs in the
download's `_internal\PySide6` folder can be replaced with your own
compatible builds. The corresponding source code for these exact versions
is available from the Qt Project:

- Qt 6.11.2: <https://download.qt.io/official_releases/qt/6.11/6.11.2/>
  (`single/` has the complete source archive, `submodules/` each module).
- PySide6 / Shiboken6 6.11.2: <https://code.qt.io/cgit/pyside/pyside-setup.git/>
  (tag `v6.11.2`), also published as a source distribution on
  <https://pypi.org/project/PySide6/6.11.2/>.

QRes GUI's own source code: <https://github.com/TheRealestNwah/qres-gui>.

The LGPL v3 is a set of additional permissions on top of the GPL v3, which is
why both texts are included.

## Expat

Copyright (c) 1998-2000 Thai Open Source Software Center Ltd and Clark Cooper
Copyright (c) 2001-2025 Expat maintainers

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## mpdecimal

Copyright (c) 2008-2024 Stefan Krah. All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions
are met:

1. Redistributions of source code must retain the above copyright
   notice, this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright
   notice, this list of conditions and the following disclaimer in the
   documentation and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE AUTHOR AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE AUTHOR OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
SUCH DAMAGE.
