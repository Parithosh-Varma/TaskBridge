import { Architecture } from "@/components/sections/Architecture";
import { Demo } from "@/components/sections/Demo";
import { Faq } from "@/components/sections/Faq";
import { Features } from "@/components/sections/Features";
import { FinalCta } from "@/components/sections/FinalCta";
import { Footer } from "@/components/sections/Footer";
import { Hero } from "@/components/sections/Hero";
import { Limitations } from "@/components/sections/Limitations";
import { Nav } from "@/components/sections/Nav";
import { Quickstart } from "@/components/sections/Quickstart";
import { Why } from "@/components/sections/Why";
import { getStarCount } from "@/lib/github";

export const revalidate = 3600;

export default async function Home() {
  const stars = await getStarCount();
  return (
    <>
      <Nav stars={stars} />
      <main id="main">
        <Hero stars={stars} />
        <Why />
        <Architecture />
        <Features />
        <Quickstart />
        <Demo />
        <Faq />
        <Limitations />
        <FinalCta stars={stars} />
      </main>
      <Footer />
    </>
  );
}
