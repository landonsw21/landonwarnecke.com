import Foundation
import PDFKit
import AppKit
// usage: pdfpages <pdf> <outprefix> <maxPages> <width>
let a = CommandLine.arguments
let url = URL(fileURLWithPath: a[1]); let prefix = a[2]; let maxP = Int(a[3])!; let w = CGFloat(Double(a[4])!)
guard let doc = PDFDocument(url: url) else { print("fail"); exit(1) }
let n = min(doc.pageCount, maxP)
for i in 0..<n {
  guard let p = doc.page(at: i) else { continue }
  let b = p.bounds(for: .mediaBox); let s = w / b.width
  let img = p.thumbnail(of: NSSize(width: b.width*s, height: b.height*s), for: .mediaBox)
  if let t = img.tiffRepresentation, let r = NSBitmapImageRep(data: t), let d = r.representation(using: .jpeg, properties: [.compressionFactor: 0.8]) {
    try? d.write(to: URL(fileURLWithPath: "\(prefix)_\(String(format: "%02d", i+1)).jpg"))
  }
}
print("pages", doc.pageCount, "rendered", n)
