/** @type {import('next').NextConfig} */
const nextConfig = {
  /**
   * `/waitlist` was the pre-launch gate: sign-up was closed and joining was a
   * request an operator approved. At general availability sign-up is open, so
   * the route is gone and its Clerk `<Waitlist />` form would error against an
   * instance that is no longer in Waitlist mode.
   *
   * The redirect stays because the links already sent out — Clerk's waitlist
   * confirmation emails, and anything anyone bookmarked — point here. A visitor
   * following one lands on the form that now does what they wanted.
   */
  async redirects() {
    return [
      { source: "/waitlist", destination: "/sign-up", permanent: true },
      { source: "/waitlist/:path*", destination: "/sign-up", permanent: true },
    ];
  },
};

export default nextConfig;
