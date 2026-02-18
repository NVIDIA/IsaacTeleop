/**
 * Parses URL parameters and returns them as an object
 * @param location - Optional location object (defaults to window.location)
 * @returns Object with URL parameters as key-value pairs
 */
export function getUrlParams(location: Location = window.location): Record<string, string> {
  const params: Record<string, string> = {};
  const queryString = location.search.substring(1);

  if (queryString) {
    const pairs = queryString.split('&');
    for (const pair of pairs) {
      const [key, value = ''] = pair.split('=');
      params[decodeURIComponent(key)] = decodeURIComponent(value);
    }
  }

  return params;
}

/**
 * Enables localStorage functionality for form elements
 * @param element - The HTML input or select element to enable localStorage for
 * @param key - The localStorage key to use for saving/loading the value
 */
export function enableLocalStorage(element: HTMLInputElement | HTMLSelectElement, key: string) {
  // Check if localStorage is already enabled for this element and key
  const localStorageKey = `__localStorageEnabled_${key}`;
  if ((element as any)[localStorageKey]) {
    console.warn(`localStorage already enabled for ${key}, skipping`);
    return;
  }

  // Load saved value from localStorage
  try {
    // Check if the key exists in localStorage, not just if it has values
    if (localStorage.hasOwnProperty(key)) {
      const savedValue = localStorage.getItem(key);
      element.value = savedValue || '';
      console.info(`Loaded saved ${key} from localStorage:`, savedValue);
    }
  } catch (error) {
    console.warn(`${key}: Failed to load saved value from localStorage:`, error);
  }

  // Set up event listener to save value when changed
  const changeHandler = () => {
    try {
      // Always save the value, even if it's empty
      localStorage.setItem(key, element.value);
      console.info(`Saved ${key} to localStorage:`, JSON.stringify(element.value));
    } catch (error) {
      console.warn(`${key}: Failed to save to localStorage:`, error);
    }
  };

  element.addEventListener('change', changeHandler);

  // Mark this element as having localStorage enabled for this key
  (element as any)[localStorageKey] = true;
}

/**
 * Sets the select value only when the option exists.
 * @param select - The select element to update
 * @param value - The value to apply if an option matches
 */
export function setSelectValueIfAvailable(select: HTMLSelectElement, value: string): void {
  const hasOption = Array.from(select.options).some(option => option.value === value);
  if (hasOption) {
    select.value = value;
  }
}

/**
 * Strips protocol prefixes (http:// or https://) from a URL string
 * @param url - The URL string to clean
 * @returns The URL without protocol prefix
 */
function stripProtocol(url: string): string {
  return url.replace(/^https?:\/\//, '');
}

/**
 * Connection configuration object containing server connection details
 */
export interface ConnectionConfiguration {
  /** Server address (proxy address when using proxy, direct server address otherwise) */
  serverIP: string;

  /** Port number (443 for HTTPS proxy, user-provided for direct connections) */
  port: number;

  /** Whether the connection will use secure protocol (HTTPS/WSS) */
  useSecureConnection: boolean;

  /** Optional resource path for proxy routing (e.g., "/192.168.1.100" for target server) */
  resourcePath?: string;
}

/**
 * CloudXR configuration interface containing all streaming settings
 */
export interface CloudXRConfig {
  /** IP address of the CloudXR streaming server */
  serverIP: string;

  /** Port number for the CloudXR server connection */
  port: number;

  /** Whether to use secure connection (HTTPS/WSS) or insecure (HTTP/WS) */
  useSecureConnection: boolean;

  /** Width of each eye in pixels (must be multiple of 16) */
  perEyeWidth: number;

  /** Height of each eye in pixels (must be multiple of 16) */
  perEyeHeight: number;

  /** Target frame rate for the XR device in frames per second (FPS) */
  deviceFrameRate: number;

  /** Maximum streaming bitrate in Megabits per second (Mbps) */
  maxStreamingBitrateMbps: number;

  /** Preferred video codec used for streaming */
  codec?: 'h264' | 'h265' | 'av1';

  /** XR immersive mode: 'ar' for augmented reality, 'vr' for virtual reality */
  immersiveMode: 'ar' | 'vr';

  /** Optional device profile identifier used by the examples UI */
  deviceProfileId?: string;

  /** Application identifier string for the CloudXR session */
  app: string;

  /** Type of server being connected to */
  serverType: string;

  /** Optional proxy URL for HTTPS routing (e.g., 'https://proxy.example.com/'); if empty, uses direct WSS connection */
  proxyUrl: string;

  /** Preferred XR reference space for tracking and positioning */
  referenceSpaceType: 'auto' | 'local-floor' | 'local' | 'viewer' | 'unbounded';

  /** XR reference space offset along X axis in meters (positive is right) */
  xrOffsetX?: number;
  /** XR reference space offset along Y axis in meters (positive is up) */
  xrOffsetY?: number;
  /** XR reference space offset along Z axis in meters (positive is backward) */
  xrOffsetZ?: number;

  /** Enable secondary position smoothing in CloudXR */
  enablePoseSmoothing?: boolean;
  /** Pose prediction factor for CloudXR (0.0-1.0) */
  posePredictionFactor?: number;
  /** Enable texSubImage2D optimization in CloudXR */
  enableTexSubImage2D?: boolean;
  /** Quest-specific color workaround in CloudXR */
  useQuestColorWorkaround?: boolean;
  /** Whether WebXR controller models should be hidden */
  hideControllerModel?: boolean;

  /** Media server address for WebRTC streaming (for NAT traversal) */
  mediaAddress?: string;

  /** Media server port for WebRTC streaming (use 0 for server-provided port) */
  mediaPort?: number;
}

/**
 * Determines connection configuration based on protocol and user inputs
 * Supports both direct WSS connections and proxy routing for HTTPS
 *
 * @param serverIP - The user-provided server IP address
 * @param port - The user-provided port number
 * @param proxyUrl - Optional proxy URL for HTTPS routing (if provided, uses proxy routing; otherwise direct connection)
 * @param location - Optional location object (defaults to window.location)
 * @returns Object containing server IP, port, security settings, and optional resource path for proxy routing
 * @throws {Error} When proxy URL format is invalid (must start with https://)
 */
export function getConnectionConfig(
  serverIP: string,
  port: number,
  proxyUrl: string,
  location: Location = window.location
): ConnectionConfiguration {
  let finalServerIP = '';
  let finalPort = port;
  let finalUseSecureConnection = false;
  let resourcePath: string | undefined = undefined;

  // Determine if we should use secure connection based on page protocol
  if (location.protocol === 'https:') {
    console.info('Running on HTTPS protocol - using secure WebSocket (WSS)');
    finalUseSecureConnection = true;

    // Check if proxy URL is provided for routing
    const trimmedProxyUrl = proxyUrl?.trim();
    if (trimmedProxyUrl) {
      // Proxy routing mode
      console.info('Proxy URL provided - using proxy routing mode');

      if (!trimmedProxyUrl.startsWith('https://')) {
        throw new Error('Proxy URL must start with https://. Received: ' + trimmedProxyUrl);
      }

      // Parse proxy URL to separate hostname from path
      const proxyUrlObj = new URL(trimmedProxyUrl);
      finalServerIP = proxyUrlObj.hostname;

      // Use proxy port if specified, otherwise default to 443
      finalPort = proxyUrlObj.port ? parseInt(proxyUrlObj.port, 10) : 443;

      // Get proxy path (remove trailing slash)
      const proxyPath = proxyUrlObj.pathname.replace(/\/$/, '');

      // Route through proxy: combine proxy path with target server IP
      if (serverIP && serverIP !== 'localhost' && serverIP !== '127.0.0.1') {
        const cleanServerIP = stripProtocol(serverIP);
        // Combine proxy path with target server: /proxy/10.28.132.185
        resourcePath = proxyPath ? `${proxyPath}/${cleanServerIP}` : `/${cleanServerIP}`;
        console.info(
          `Using HTTPS proxy: ${finalServerIP}:${finalPort} with resource path: ${resourcePath}`
        );
      } else {
        // No target server, just use proxy path if any
        resourcePath = proxyPath || undefined;
        console.info(
          `Using HTTPS proxy: ${finalServerIP}:${finalPort} (no target server specified)`
        );
      }
    } else {
      // Direct WSS connection mode
      console.info('No proxy URL - using direct WSS connection');

      // Handle server IP input
      if (serverIP && serverIP !== 'localhost' && serverIP !== '127.0.0.1') {
        finalServerIP = stripProtocol(serverIP);
        console.info('Using user-provided server IP:', finalServerIP);
      } else {
        finalServerIP = new URL(location.href).hostname;
        console.info('Using default server IP from window location:', finalServerIP);
      }

      // Use user-provided port for direct WSS
      if (port && !isNaN(port)) {
        finalPort = port;
        console.info('Using user-provided port:', finalPort);
      }
    }
  } else {
    // HTTP protocol - direct WS connection
    console.info('Running on HTTP protocol - using insecure WebSocket (WS)');
    finalUseSecureConnection = false;

    // Handle server IP input
    if (serverIP && serverIP !== 'localhost' && serverIP !== '127.0.0.1') {
      finalServerIP = stripProtocol(serverIP);
      console.info('Using user-provided server IP:', finalServerIP);
    } else {
      finalServerIP = new URL(location.href).hostname;
      console.info('Using default server IP from window location:', finalServerIP);
    }

    // Handle port input
    if (port && !isNaN(port)) {
      finalPort = port;
      console.info('Using user-provided port:', finalPort);
    }
  }

  return {
    serverIP: finalServerIP,
    port: finalPort,
    useSecureConnection: finalUseSecureConnection,
    resourcePath,
  } as ConnectionConfiguration;
}

/**
 * Sets up certificate acceptance link for self-signed certificates in HTTPS mode
 * Shows a link to accept certificates when using direct WSS connection (no proxy)
 *
 * @param serverIpInput - Input element for server IP address
 * @param portInput - Input element for port number
 * @param proxyUrlInput - Input element for proxy URL
 * @param certAcceptanceLink - Container element for the certificate link
 * @param certLink - Anchor element for the certificate URL
 * @param location - Optional location object (defaults to window.location)
 * @returns Cleanup function to remove event listeners
 */
export function setupCertificateAcceptanceLink(
  serverIpInput: HTMLInputElement,
  portInput: HTMLInputElement,
  proxyUrlInput: HTMLInputElement,
  certAcceptanceLink: HTMLElement,
  certLink: HTMLAnchorElement,
  location: Location = window.location
): () => void {
  /**
   * Updates the certificate acceptance link based on current configuration
   * Shows link only when in HTTPS mode without proxy (direct WSS)
   */
  const updateCertLink = () => {
    const isHttps = location.protocol === 'https:';
    const hasProxy = proxyUrlInput.value.trim().length > 0;
    const portValue = parseInt(portInput.value, 10);
    const defaultPort = hasProxy ? 443 : 48322;
    const port = portValue || defaultPort;

    // Show link only in HTTPS mode without proxy
    if (isHttps && !hasProxy) {
      let serverIp = serverIpInput.value.trim();
      if (!serverIp) {
        serverIp = new URL(location.href).hostname;
      }
      const url = `https://${serverIp}:${port}/`;
      certAcceptanceLink.style.display = 'block';
      certLink.href = url;
      certLink.textContent = `Click ${url} to accept cert`;
    } else {
      certAcceptanceLink.style.display = 'none';
    }
  };

  // Add event listeners to update link when inputs change
  serverIpInput.addEventListener('input', updateCertLink);
  portInput.addEventListener('input', updateCertLink);
  proxyUrlInput.addEventListener('input', updateCertLink);

  // Initial update after localStorage values are restored
  setTimeout(updateCertLink, 0);

  // Return cleanup function to remove event listeners
  return () => {
    serverIpInput.removeEventListener('input', updateCertLink);
    portInput.removeEventListener('input', updateCertLink);
    proxyUrlInput.removeEventListener('input', updateCertLink);
  };
}
