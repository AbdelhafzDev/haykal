# Third-party notices

Haykal's core package does not bundle model weights. The optional, offline
OmniParser cache preparation command downloads only the files pinned in
`config/models/omniparser-v2.json` and retains their license files.

## Microsoft OmniParser V2

The detector decoding in `haykal.perception.omniparser_v2` is adapted from
Microsoft OmniParser commit `354021201345a96178360b28733573e27269f2de`.
The `icon_detect_v3` detector and `icon_caption` model files pinned by Haykal are
published under the MIT License. Haykal intentionally does not use the older
Ultralytics-based `icon_detect` bundle.

Copyright (c) Microsoft Corporation.

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
the Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Microsoft Florence-2 processor

The pinned Florence-2 repository declares MIT licensing. Its
`configuration_florence2.py`, `modeling_florence2.py`, and
`processing_florence2.py` files carry Apache License 2.0 headers and are recorded
as Apache-2.0 in Haykal's model manifest. The cache also retains the upstream
license file. Apache License 2.0 is available at
<https://www.apache.org/licenses/LICENSE-2.0>.
