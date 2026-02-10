/**
 * Override PressureObserver to catch errors from unexpected browser implementations.
 *
 * Some browsers have buggy PressureObserver implementations that throw errors
 * when observe() is called. This wrapper catches and logs those errors instead
 * of letting them propagate.
 *
 * This should be called early in your application, before any code attempts
 * to use PressureObserver.
 */
export function overridePressureObserver(): void {
  if (typeof window === 'undefined' || !(window as any).PressureObserver) {
    return;
  }

  const OriginalPressureObserver = (window as any).PressureObserver;

  (window as any).PressureObserver = class PressureObserver extends OriginalPressureObserver {
    observe(source: any) {
      try {
        const result = super.observe(source);
        if (result && typeof result.catch === 'function') {
          return result.catch((e: Error) => {
            console.warn('PressureObserver.observe() failed:', e.message);
            return undefined;
          });
        }
        return result;
      } catch (e: any) {
        console.warn('PressureObserver.observe() failed:', e.message);
        return undefined;
      }
    }
  };
}
