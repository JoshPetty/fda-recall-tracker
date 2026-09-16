import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Link } from 'expo-router';

import { supabase } from '../../lib/supabase';

type RecallRow = {
  id: string;
  product_name: string;
  brand: string | null;
  hazard_classification: string | null;
  date_initiated: string | null;
};

// 'all' / 'nationwide' / 'unparsed' are fixed filter options; any other
// string is a 2-letter state code from recall_states.
type Filter = 'all' | 'nationwide' | 'unparsed' | string;

const STATE_NAMES: Record<string, string> = {
  AL: 'Alabama', AK: 'Alaska', AZ: 'Arizona', AR: 'Arkansas', CA: 'California',
  CO: 'Colorado', CT: 'Connecticut', DE: 'Delaware', FL: 'Florida', GA: 'Georgia',
  HI: 'Hawaii', ID: 'Idaho', IL: 'Illinois', IN: 'Indiana', IA: 'Iowa',
  KS: 'Kansas', KY: 'Kentucky', LA: 'Louisiana', ME: 'Maine', MD: 'Maryland',
  MA: 'Massachusetts', MI: 'Michigan', MN: 'Minnesota', MS: 'Mississippi', MO: 'Missouri',
  MT: 'Montana', NE: 'Nebraska', NV: 'Nevada', NH: 'New Hampshire', NJ: 'New Jersey',
  NM: 'New Mexico', NY: 'New York', NC: 'North Carolina', ND: 'North Dakota', OH: 'Ohio',
  OK: 'Oklahoma', OR: 'Oregon', PA: 'Pennsylvania', RI: 'Rhode Island', SC: 'South Carolina',
  SD: 'South Dakota', TN: 'Tennessee', TX: 'Texas', UT: 'Utah', VT: 'Vermont',
  VA: 'Virginia', WA: 'Washington', WV: 'West Virginia', WI: 'Wisconsin', WY: 'Wyoming',
  DC: 'District of Columbia',
};

const PAGE_SIZE = 25;

export default function RecallsListScreen() {
  const [recalls, setRecalls] = useState<RecallRow[]>([]);
  const [page, setPage] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [availableStates, setAvailableStates] = useState<string[]>([]);
  const [filter, setFilter] = useState<Filter>('all');
  const [isFilterOpen, setIsFilterOpen] = useState(false);

  // States that actually appear in recall_states, for the filter list --
  // not the full fixed 51-code set, so there's nothing to pick that would
  // always come back empty.
  useEffect(() => {
    supabase
      .from('recall_states')
      .select('state_code')
      .then(({ data, error: statesError }) => {
        if (statesError || !data) return;
        const unique = Array.from(new Set(data.map((row) => row.state_code as string))).sort();
        setAvailableStates(unique);
      });
  }, []);

  const loadPage = useCallback(async (pageToLoad: number, activeFilter: Filter) => {
    const from = pageToLoad * PAGE_SIZE;
    const to = from + PAGE_SIZE - 1;

    let result;

    if (activeFilter === 'all') {
      result = await supabase
        .from('recalls')
        .select('id, product_name, brand, hazard_classification, date_initiated')
        .order('date_initiated', { ascending: false })
        .range(from, to);
    } else if (activeFilter === 'nationwide') {
      result = await supabase
        .from('recalls')
        .select('id, product_name, brand, hazard_classification, date_initiated')
        .eq('is_nationwide', true)
        .order('date_initiated', { ascending: false })
        .range(from, to);
    } else if (activeFilter === 'unparsed') {
      result = await supabase
        .from('recalls')
        .select('id, product_name, brand, hazard_classification, date_initiated')
        .eq('parse_status', 'unparsed')
        .order('date_initiated', { ascending: false })
        .range(from, to);
    } else {
      // A specific state code: only recalls with a matching recall_states
      // row. `!inner` makes this an inner join, so the state_code filter
      // actually restricts the parent rows instead of just nulling out
      // an unmatched left join.
      result = await supabase
        .from('recalls')
        .select('id, product_name, brand, hazard_classification, date_initiated, recall_states!inner(state_code)')
        .eq('recall_states.state_code', activeFilter)
        .order('date_initiated', { ascending: false })
        .range(from, to);
    }

    const { data, error: queryError } = result;

    if (queryError) {
      setError(queryError.message);
      return;
    }

    const rows = (data ?? []) as RecallRow[];
    setRecalls((prev) => (pageToLoad === 0 ? rows : [...prev, ...rows]));
    setHasMore(rows.length === PAGE_SIZE);
  }, []);

  useEffect(() => {
    setIsLoading(true);
    setPage(0);
    setHasMore(true);
    loadPage(0, filter).finally(() => setIsLoading(false));
  }, [filter, loadPage]);

  const handleLoadMore = async () => {
    if (isLoadingMore || !hasMore || isLoading) return;
    setIsLoadingMore(true);
    const nextPage = page + 1;
    await loadPage(nextPage, filter);
    setPage(nextPage);
    setIsLoadingMore(false);
  };

  const filterLabel =
    filter === 'all'
      ? 'All states'
      : filter === 'nationwide'
        ? 'Nationwide'
        : filter === 'unparsed'
          ? 'Unknown or other'
          : STATE_NAMES[filter] ?? filter;

  const filterOptions: { value: Filter; label: string }[] = [
    { value: 'all', label: 'All states' },
    { value: 'nationwide', label: 'Nationwide' },
    ...availableStates.map((code) => ({ value: code, label: STATE_NAMES[code] ?? code })),
    { value: 'unparsed', label: 'Unknown or other' },
  ];

  return (
    <View style={styles.container}>
      <Link href="/" style={styles.back}>
        Back
      </Link>
      <Text style={styles.title}>Recalls</Text>

      <Pressable style={styles.filterButton} onPress={() => setIsFilterOpen((open) => !open)}>
        <Text style={styles.filterButtonText}>Filter: {filterLabel}</Text>
      </Pressable>

      {isFilterOpen ? (
        <ScrollView style={styles.filterList}>
          {filterOptions.map((option) => (
            <Pressable
              key={option.value}
              style={styles.filterOption}
              onPress={() => {
                setFilter(option.value);
                setIsFilterOpen(false);
              }}
            >
              <Text
                style={option.value === filter ? styles.filterOptionSelected : styles.filterOptionText}
              >
                {option.label}
              </Text>
            </Pressable>
          ))}
        </ScrollView>
      ) : null}

      {isLoading ? (
        <View style={styles.centered}>
          <ActivityIndicator />
        </View>
      ) : error ? (
        <Text style={styles.error}>{error}</Text>
      ) : recalls.length === 0 ? (
        <Text style={styles.body}>
          {filter === 'all' ? 'No recalls found.' : 'No recalls found for this filter.'}
        </Text>
      ) : (
        <FlatList
          data={recalls}
          keyExtractor={(item) => item.id}
          onEndReached={handleLoadMore}
          onEndReachedThreshold={0.5}
          ItemSeparatorComponent={() => <View style={styles.separator} />}
          renderItem={({ item }) => (
            <Link href={`/recalls/${item.id}`} asChild>
              <Pressable style={styles.row}>
                <Text style={styles.rowTitle}>{item.product_name}</Text>
                <Text style={styles.rowMeta}>{item.brand ?? 'Unknown brand'}</Text>
                <Text style={styles.rowMeta}>{item.hazard_classification ?? 'Unclassified'}</Text>
                <Text style={styles.rowMeta}>{item.date_initiated ?? 'No date on file'}</Text>
              </Pressable>
            </Link>
          )}
          ListFooterComponent={isLoadingMore ? <ActivityIndicator style={styles.footer} /> : null}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: 24,
    gap: 12,
  },
  back: {
    fontSize: 16,
  },
  title: {
    fontSize: 20,
    fontWeight: '600',
  },
  filterButton: {
    borderWidth: 1,
    borderColor: '#ccc',
    borderRadius: 4,
    paddingVertical: 10,
    paddingHorizontal: 12,
    alignSelf: 'flex-start',
  },
  filterButtonText: {
    fontSize: 14,
  },
  filterList: {
    maxHeight: 240,
    borderWidth: 1,
    borderColor: '#ccc',
    borderRadius: 4,
  },
  filterOption: {
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#eee',
  },
  filterOptionText: {
    fontSize: 14,
  },
  filterOptionSelected: {
    fontSize: 14,
    fontWeight: '600',
  },
  centered: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  body: {
    fontSize: 16,
  },
  error: {
    color: '#c0392b',
  },
  row: {
    paddingVertical: 12,
    gap: 4,
  },
  rowTitle: {
    fontSize: 16,
    fontWeight: '600',
  },
  rowMeta: {
    fontSize: 14,
    color: '#555',
  },
  separator: {
    height: 1,
    backgroundColor: '#ddd',
  },
  footer: {
    paddingVertical: 16,
  },
});
