// Twitter/X uses the same card as Open Graph. Re-export the generator so
// there is one image to maintain and both meta tags are emitted.
export { default, alt, size, contentType } from "./opengraph-image";
