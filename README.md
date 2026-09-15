# Evrit Metadata Source Plugin for Calibre

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Calibre](https://img.shields.io/badge/calibre-plugin-green.svg)](https://calibre-ebook.com/)

A metadata source plugin for **[Calibre](https://calibre-ebook.com/)** that automatically fetches book information, ratings, and high-resolution cover art from the Israeli Hebrew e-book store **[Evrit (עברית)](https://www.e-vrit.co.il/)**.

---

## Features

- **Rich Metadata Extraction**:
  - **Title & Authors** (with Hebrew punctuation and abbreviation tolerance).
  - **Publisher** & **Publication Date**.
  - **Comments / Summary** (full rich-text synopsis).
  - **Tags & Genres** (drawn from store category lists and content tags).
  - **Series Name** (when part of a known book series).
  - **User Ratings** (synced from store community reviews).
- **High-Resolution Cover Art**: Retrieves high-quality cover images (up to 1200px width) directly from the Cloudflare CDN.
- **Hebrew Matching Engine**:
  - Tolerant of *Ktiv Haser* vs. *Ktiv Male* (ignores optional 'אהוי' discrepancies).
  - Handles unicode directional marks (e.g. LRM U+200E).
  - Normalizes Geresh (`'`), Gershayim (`"`), dashes, colons, and subtitles.
  - Levenshtein distance ranking to select the most accurate match.
- **Calibre Identifier**: Stores the identifier as `evrit:<id>` (displays as **עברית** in Calibre details).

---

## Attribution & Acknowledgements

This project is a continuation and maintenance fork of the original **Evrit** metadata plugin:

* **Original Author**: Special thanks and full credit to **HebrewReader** (`hebrew.reader.calibre@gmail.com`), who originally created the plugin in 2023 and developed versions 1.0.0 through 1.4.0.
* **Original Discussion**: [MobileRead Thread #351377: [Metadata Source Plugin] Evrit](https://www.mobileread.com/forums/showthread.php?t=351377).
* **Community Contributors**: Thanks to MobileRead members `theducks`, `BetterRed`, and `tgiladi` for their testing, feedback, and contributions during initial development.
* **Version 2.0.0 Update**: Following the complete redesign and migration of `e-vrit.co.il` to a Next.js platform (which caused all legacy ASP.NET endpoints to return 404 errors), this repository updates the plugin with:
  - Integration with the new `POST /api/search` endpoint and browser WAF header handling.
  - Structured metadata parsing using Schema.org JSON-LD (`@type: "Book"`).
  - Enrichment from the new Next.js `/api/product/extra/{id}` endpoints for descriptions, tags, and series.
  - Enhanced Cloudflare CDN cover image resolution (up to 1200px).

---

## Installation

### Method 1: Install from Release (.zip)
1. Download the latest `Evrit.zip` from the [Releases](../../releases) tab.
2. Open **Calibre**.
3. Go to **Preferences** (`Ctrl + P`) → **Plugins**.
4. Click **Load plugin from file** (bottom right).
5. Select `Evrit.zip` and click **Open**.
6. When prompted with the security warning, click **Yes** to confirm installation.
7. Restart Calibre.

### Method 2: Development / Source Installation
If you have Calibre's command-line tools installed, you can build and load the plugin directly from this cloned directory:

```bash
# From the repository root
calibre-customize -b .
```

To verify the installation:
```bash
calibre-customize -l | grep Evrit
```

---

## Building from Source

To create the distributable `Evrit.zip` package manually:

### PowerShell (Windows)
```powershell
Compress-Archive -Path __init__.py, version_history.txt -DestinationPath Evrit.zip -Force
```

### Bash (Linux / macOS)
```bash
zip -9 Evrit.zip __init__.py version_history.txt
```

> **Note**: The `.zip` file must contain `__init__.py` at the root of the archive (not inside a subfolder).

---

## Usage

1. Select one or more Hebrew books in your Calibre library.
2. Press **`E`** (or right-click → **Edit metadata** → **Edit metadata individually**).
3. Click **Download metadata** or **Download cover**.
4. To configure priorities or enable/disable Evrit:
   * Go to **Preferences** → **Metadata download**.
   * Select **Evrit** in the list of sources to configure or test.

### Debugging & Logs
If you encounter any issues or want to inspect network requests:
* Run Calibre in debug mode from terminal:
  ```bash
  calibre-debug -g
  ```
* Or inside Calibre: Click the arrow next to **Preferences** → **Restart in debug mode**.

---

## Version History

See [version_history.txt](version_history.txt) for the complete changelog from version 1.0.0 to present.

---

## License

This project is licensed under the **GNU General Public License v3.0** (GPLv3), matching Calibre's core license. See the [LICENSE](LICENSE) file for details.
