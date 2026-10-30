import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Guardian Gateway",
  description: "Distributed API gateway administration dashboard",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
