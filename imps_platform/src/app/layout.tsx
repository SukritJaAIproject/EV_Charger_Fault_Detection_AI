"use client";

import React from "react";
import ThemeProvider from "@/components/ThemeProvider";
import theme from "@/theme";
import { MaterialTailwindControllerProvider } from "@/context";
import InnerContent from "./content";
import { Kanit, Plus_Jakarta_Sans, JetBrains_Mono } from "next/font/google";
import "@fortawesome/fontawesome-free/css/fontawesome.min.css";
import "@fortawesome/fontawesome-free/css/solid.min.css";
import "@fortawesome/fontawesome-free/css/brands.min.css";
import "react-calendar/dist/Calendar.css";
import "./globals.css";

const kanit = Kanit({
  subsets: ["thai", "latin"],
  weight: ["400", "500", "600", "700", "800"],
  variable: "--font-kanit",
  display: "swap",
});

const jakarta = Plus_Jakarta_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
  variable: "--font-jakarta",
  display: "swap",
});

const jetbrains = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-mono",
  display: "swap",
});

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="th" className={`${kanit.variable} ${jakarta.variable} ${jetbrains.variable}`}>
      <head>
        <link rel="icon" type="image/png" href="/img/favicon.png" />
        <title>iMPS</title>
      </head>
      <body className={kanit.className}>
        <ThemeProvider value={theme}>
          <MaterialTailwindControllerProvider>
            <InnerContent>{children}</InnerContent>
          </MaterialTailwindControllerProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
