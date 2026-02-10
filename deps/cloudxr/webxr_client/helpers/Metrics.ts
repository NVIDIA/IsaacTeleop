/**
 * A fast windowed average tracker using a dual-window approach.
 * This provides efficient rolling average calculation with approximate window size.
 *
 * This is not thread safe.
 */
export class FastWindowedAverage {
  // The minimum window size for the filter. Max window size is 2 * minWindowSize.
  private readonly minWindowSize: number;

  // Tracking for the old window
  private oldWindowSum: number = 0;
  private oldWindowCount: number = 0;

  // Tracking for the new window
  private newWindowSum: number = 0;
  private newWindowCount: number = 0;

  /**
   * Creates a new FastWindowedAverage instance
   * @param minWindowSize The minimum window size for tracking
   */
  constructor(minWindowSize: number) {
    this.minWindowSize = minWindowSize;
  }

  /**
   * Inserts a new value into the window
   * @param value The value to insert
   */
  insert(value: number): void {
    // Add the value to the new window
    this.newWindowSum += value;
    this.newWindowCount++;

    // If the new window is full, swap the windows
    if (this.newWindowCount === this.minWindowSize) {
      // Move new window to old window
      this.oldWindowSum = this.newWindowSum;
      this.oldWindowCount = this.newWindowCount;

      // Reset new window
      this.newWindowSum = 0;
      this.newWindowCount = 0;
    }
  }

  /**
   * Gets the current average value across both windows
   * @returns The current average value, or null if no values have been inserted
   */
  get(): number | null {
    const totalSum = this.oldWindowSum + this.newWindowSum;
    const totalCount = this.oldWindowCount + this.newWindowCount;

    if (totalCount === 0) {
      return null;
    }

    return totalSum / totalCount;
  }

  /**
   * Gets the current count of values in the tracking windows
   * @returns The total number of values currently being tracked
   */
  getCount(): number {
    return this.oldWindowCount + this.newWindowCount;
  }

  /**
   * Resets the average tracker to initial state
   */
  reset(): void {
    this.oldWindowSum = 0;
    this.oldWindowCount = 0;
    this.newWindowSum = 0;
    this.newWindowCount = 0;
  }
}

/**
 * A metrics tracker that maintains windowed average statistics for a metric value.
 * Tracks average values over a sliding window using a fast dual-window approach.
 *
 * @example
 * ```typescript
 * const tracker = new MetricsTracker(100);
 * const avg1 = tracker.add(42);  // Returns 42
 * const avg2 = tracker.add(55);  // Returns 48.5
 * console.log(tracker.getAverage()); // 48.5
 * ```
 */
export class MetricsTracker {
  private readonly averageTracker: FastWindowedAverage;

  /**
   * Creates a new MetricsTracker instance
   * @param windowSize The window size for tracking statistics (default: 100)
   */
  constructor(windowSize: number = 100) {
    this.averageTracker = new FastWindowedAverage(windowSize);
  }

  /**
   * Adds a new metric value to the tracker
   * @param value The metric value to add
   * @returns The current average after adding the value
   */
  add(value: number): number {
    this.averageTracker.insert(value);
    return this.averageTracker.get() ?? 0;
  }

  /**
   * Gets the average value in the current window
   * @returns The average value, or null if no values have been added
   */
  getAverage(): number | null {
    return this.averageTracker.get();
  }

  /**
   * Resets the tracker to initial state
   */
  reset(): void {
    this.averageTracker.reset();
  }
}
