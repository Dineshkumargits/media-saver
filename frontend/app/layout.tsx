import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Media Saver — Download from YouTube, Instagram & more",
  description: "Self-hosted media downloader with direct, high-quality streaming.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
