// An 8-bit text renderer, drawn a pixel at a time.
//
// The battle screen needs lettering that looks like it came off a cartridge,
// and this machine has no scalable pixel font installed - the .fon bitmaps
// that are here render at one fixed size and refuse to grow. So the font is
// in this file: an original 5x7 uppercase face, one glyph per string of dots
// and hashes, painted onto a Canvas as filled squares.
//
// Drawing it ourselves buys three things a font file would not. It is crisp
// at any size, because a "pixel" is however many real pixels `pixel` says it
// is and nothing is ever interpolated. It scales with the monitor rather than
// with fontconfig. And it carries no licence, which the rest of this feature
// also has to be able to say.
//
// Lowercase is folded to uppercase on the way in, the way the machines this
// is imitating did, and anything with no glyph comes out as a hollow box so a
// missing character is visible rather than silent.

import QtQuick
import qs.Commons

Item {
    id: root

    property string text: ""
    // The size of one font pixel, in real pixels. Everything else follows.
    property int pixel: 3
    property color color: Color.foreground
    // A hard offset shadow, the way a sprite font gets its contrast against a
    // busy background. Set the alpha to 0 to turn it off.
    property color shadowColor: Qt.rgba(0, 0, 0, 0.55)
    property int shadowOffset: 1
    // Wrap at this many characters; 0 means never wrap.
    property int columns: 0
    property int lineGap: 3

    readonly property int glyphWidth: 5
    readonly property int glyphHeight: 7
    readonly property int advance: glyphWidth + 1

    // The font. Seven rows of five, '#' where a pixel is lit.
    readonly property var glyphs: ({
        "A": ".###.|#...#|#...#|#####|#...#|#...#|#...#",
        "B": "####.|#...#|#...#|####.|#...#|#...#|####.",
        "C": ".###.|#...#|#....|#....|#....|#...#|.###.",
        "D": "####.|#...#|#...#|#...#|#...#|#...#|####.",
        "E": "#####|#....|#....|####.|#....|#....|#####",
        "F": "#####|#....|#....|####.|#....|#....|#....",
        "G": ".###.|#...#|#....|#.###|#...#|#...#|.###.",
        "H": "#...#|#...#|#...#|#####|#...#|#...#|#...#",
        "I": "#####|..#..|..#..|..#..|..#..|..#..|#####",
        "J": "..###|...#.|...#.|...#.|...#.|#..#.|.##..",
        "K": "#...#|#..#.|#.#..|##...|#.#..|#..#.|#...#",
        "L": "#....|#....|#....|#....|#....|#....|#####",
        "M": "#...#|##.##|#.#.#|#...#|#...#|#...#|#...#",
        "N": "#...#|##..#|#.#.#|#..##|#...#|#...#|#...#",
        "O": ".###.|#...#|#...#|#...#|#...#|#...#|.###.",
        "P": "####.|#...#|#...#|####.|#....|#....|#....",
        "Q": ".###.|#...#|#...#|#...#|#.#.#|#..#.|.##.#",
        "R": "####.|#...#|#...#|####.|#.#..|#..#.|#...#",
        "S": ".####|#....|#....|.###.|....#|....#|####.",
        "T": "#####|..#..|..#..|..#..|..#..|..#..|..#..",
        "U": "#...#|#...#|#...#|#...#|#...#|#...#|.###.",
        "V": "#...#|#...#|#...#|#...#|#...#|.#.#.|..#..",
        "W": "#...#|#...#|#...#|#...#|#.#.#|##.##|#...#",
        "X": "#...#|#...#|.#.#.|..#..|.#.#.|#...#|#...#",
        "Y": "#...#|#...#|.#.#.|..#..|..#..|..#..|..#..",
        "Z": "#####|....#|...#.|..#..|.#...|#....|#####",
        "0": ".###.|#...#|#..##|#.#.#|##..#|#...#|.###.",
        "1": "..#..|.##..|..#..|..#..|..#..|..#..|.###.",
        "2": ".###.|#...#|....#|...#.|..#..|.#...|#####",
        "3": "#####|...#.|..#..|...#.|....#|#...#|.###.",
        "4": "...#.|..##.|.#.#.|#..#.|#####|...#.|...#.",
        "5": "#####|#....|####.|....#|....#|#...#|.###.",
        "6": "..##.|.#...|#....|####.|#...#|#...#|.###.",
        "7": "#####|....#|...#.|..#..|.#...|.#...|.#...",
        "8": ".###.|#...#|#...#|.###.|#...#|#...#|.###.",
        "9": ".###.|#...#|#...#|.####|....#|...#.|.##..",
        " ": ".....|.....|.....|.....|.....|.....|.....",
        ".": ".....|.....|.....|.....|.....|.##..|.##..",
        ",": ".....|.....|.....|.....|.##..|.##..|.#...",
        "!": "..#..|..#..|..#..|..#..|..#..|.....|..#..",
        "?": ".###.|#...#|....#|...#.|..#..|.....|..#..",
        "'": "..#..|..#..|.....|.....|.....|.....|.....",
        "-": ".....|.....|.....|#####|.....|.....|.....",
        "_": ".....|.....|.....|.....|.....|.....|#####",
        "=": ".....|.....|#####|.....|#####|.....|.....",
        "+": ".....|..#..|..#..|#####|..#..|..#..|.....",
        ":": ".....|.##..|.##..|.....|.##..|.##..|.....",
        ";": ".....|.##..|.##..|.....|.##..|.##..|.#...",
        "/": "....#|...#.|..#..|..#..|.#...|#....|.....",
        "\\": "#....|.#...|..#..|..#..|...#.|....#|.....",
        "(": "...#.|..#..|.#...|.#...|.#...|..#..|...#.",
        ")": ".#...|..#..|...#.|...#.|...#.|..#..|.#...",
        "[": "..##.|..#..|..#..|..#..|..#..|..#..|..##.",
        "]": ".##..|..#..|..#..|..#..|..#..|..#..|.##..",
        "<": "...#.|..#..|.#...|#....|.#...|..#..|...#.",
        ">": ".#...|..#..|...#.|....#|...#.|..#..|.#...",
        "*": ".....|#.#.#|.###.|#####|.###.|#.#.#|.....",
        "%": "##..#|##.#.|...#.|..#..|.#...|#.###|..###",
        "#": ".#.#.|#####|.#.#.|.#.#.|#####|.#.#.|.....",
        "@": ".###.|#...#|#.###|#.#.#|#.###|#....|.###.",
        "&": ".##..|#..#.|.##..|.##.#|#..#.|#...#|.###.",
        "|": "..#..|..#..|..#..|..#..|..#..|..#..|..#..",
        "\"": ".#.#.|.#.#.|.....|.....|.....|.....|....."
    })

    readonly property string missing: "#####|#...#|#...#|#...#|#...#|#...#|#####"

    // The text broken into lines: explicit newlines first, then word wrap.
    readonly property var lines: {
        var source = String(root.text || "").toUpperCase()
        var out = []
        var paragraphs = source.split("\n")
        for (var p = 0; p < paragraphs.length; p++) {
            if (root.columns <= 0) {
                out.push(paragraphs[p])
                continue
            }
            var words = paragraphs[p].split(" ")
            var current = ""
            for (var w = 0; w < words.length; w++) {
                var candidate = current === "" ? words[w] : current + " " + words[w]
                if (candidate.length <= root.columns) {
                    current = candidate
                } else {
                    if (current !== "") out.push(current)
                    // A single word longer than the line is cut rather than
                    // allowed to run off the edge of the box.
                    while (words[w].length > root.columns) {
                        out.push(words[w].substring(0, root.columns))
                        words[w] = words[w].substring(root.columns)
                    }
                    current = words[w]
                }
            }
            out.push(current)
        }
        return out
    }

    readonly property int longest: {
        var most = 0
        for (var i = 0; i < lines.length; i++) most = Math.max(most, lines[i].length)
        return most
    }

    implicitWidth: longest > 0 ? longest * advance * pixel - pixel : 0
    implicitHeight: lines.length > 0
        ? lines.length * glyphHeight * pixel + (lines.length - 1) * lineGap * pixel
        : 0

    onLinesChanged: canvas.requestPaint()
    onPixelChanged: canvas.requestPaint()
    onColorChanged: canvas.requestPaint()
    onShadowColorChanged: canvas.requestPaint()

    Canvas {
        id: canvas

        anchors.fill: parent
        // The shadow sits one font pixel outside the text box, so the canvas
        // is grown to make room for it rather than clipping it away.
        anchors.margins: -root.pixel * root.shadowOffset
        renderStrategy: Canvas.Cooperative

        onPaint: {
            var context = getContext("2d")
            context.reset()
            var offset = root.pixel * root.shadowOffset
            if (root.shadowColor.a > 0)
                root.paintText(context, offset + offset, offset + offset, root.shadowColor)
            root.paintText(context, offset, offset, root.color)
        }
    }

    function paintText(context, originX, originY, ink) {
        context.fillStyle = ink
        var size = root.pixel
        for (var line = 0; line < root.lines.length; line++) {
            var top = originY + line * (root.glyphHeight + root.lineGap) * size
            var text = root.lines[line]
            for (var index = 0; index < text.length; index++) {
                var glyph = root.glyphs[text.charAt(index)]
                if (glyph === undefined) glyph = root.missing
                if (glyph === root.glyphs[" "]) continue
                var left = originX + index * root.advance * size
                var rows = glyph.split("|")
                for (var row = 0; row < rows.length; row++) {
                    for (var column = 0; column < rows[row].length; column++) {
                        if (rows[row].charAt(column) !== "#") continue
                        context.fillRect(left + column * size, top + row * size,
                                         size, size)
                    }
                }
            }
        }
    }
}
