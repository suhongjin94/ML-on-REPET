import librosa, numpy as np, scipy as sp, os, nussl, mir_eval, sqlite3, matplotlib.pyplot as plt, sys

def wavwrite(filepath, data, sr, norm=True, dtype='int16',):
    '''
    Write wave file using scipy.io.wavefile.write, converting from a float (-1.0 : 1.0) numpy array to an integer array
    
    Parameters
    ----------
    filepath : str
        The path of the output .wav file
    data : np.array
        The float-type audio array
    sr : int
        The sampling rate
    norm : bool
        If True, normalize the audio to -1.0 to 1.0 before converting integer
    dtype : str
        The output type. Typically leave this at the default of 'int16'.
    '''
    if norm:
        data /= np.max(np.abs(data))
    data = data * np.iinfo(dtype).max
    data = data.astype(dtype)
    sp.io.wavfile.write(filepath, sr, data)

def save_foreground(input_path, output_path, length, sample_rate):
    '''
    Shorten wave files to a specified length

    Parameters
    ----------
    input_path : str
        the path of the input file
    length : int
        length in seconds of the output file
    output_path : str
        the path of the output file
    '''
    print 'loading fg file...'
    fg, sample_rate = librosa.load(input_path, sr=sample_rate)
    print 'shortening fg file....'
    fg = fg[:length * sample_rate]
    print 'writing fg...' 
    wavwrite(output_path, fg, sample_rate)

def save_background(input_path, output_path, sample_rate, length=0, number_of_repeating_segments=0):
    '''
    Stitch together wave files to a specified length

    Parameters
    ----------
    input_path : str
        the path of the input file
    length : int
        length in seconds of the output file
    output_path : str
        the path of the output file
    '''
    print 'loading bg file...'
    bg, sample_rate = librosa.load(input_path, sr=sample_rate)
    print 'stitching bg file...'
    if length > 0:
        bg_length = bg.shape[0] / sample_rate
        number_of_segments = int(np.ceil(length / bg_length))
    elif number_of_repeating_segments > 0:
        number_of_segments = number_of_repeating_segments
    else:
        print 'a length or number of repeating segments must be specified'
        return
    
    result = bg
    for i in range(0, number_of_segments):
        result = np.concatenate((bg, result))

    print 'writing bg...' 
    wavwrite(output_path, result, sample_rate)

def pre_process_background(start, end):
    '''
    Process background files

    Parameters
    ----------
    start : int
        start index for numbered sound files
    end : int
        one more than the end index for numbered sound files
    '''
    for i in range(start, end):
        length = 30
        number_of_repeating_segments = 10
        save_background('../bg/bg-%02d.wav' % i, '../bg/beat-spectrum-processed/bg-%02d.wav' % i, 44100, number_of_repeating_segments=10)

def pre_process_background(input_path, output_path, number_of_repeating_segments):
    files = os.listdir(input_path)

    for f in files:
        if os.path.isfile(os.path.join(input_path, f)):
            save_background(os.path.join(input_path, f), os.path.join(output_path, f), 44100, number_of_repeating_segments)

def run_repet(X, window_size=None, window_type=None, period=None):
    ''' 
    runs REPET on a signal with given parameters

    Parameters
    ----------
    X : 1D numpy array
        the time series of a signal
    window_size : int
        size of the window used for Fourier Transform
    window_type : nussl.WindowType
        type of window used in the stft transformation
    '''
    signal = nussl.AudioSignal(audio_data_array=X)

    signal.window_length = window_size
    signal.window_type = window_type

    params = nussl.StftParams(signal.sample_rate, window_length=window_size, window_type=window_type)
    repet = nussl.Repet(signal, repet_type=nussl.RepetType.DEFAULT, stft_params=params)
    beat_spectrum = repet.get_beat_spectrum()

    period_simple = nussl.Repet.find_repeating_period_simple(beat_spectrum, repet.min_period, repet.max_period)
    period_complex = float(nussl.Repet.find_repeating_period_complex(beat_spectrum))

    repet = nussl.Repet(signal, repet_type=nussl.RepetType.DEFAULT, min_period=1, period=period_simple, max_period=len(beat_spectrum))
    repet.update_periods()

    print period_simple
    print repet.period

    repet.run()
    bg_simple, fg_simple = repet.make_audio_signals()

    repet = nussl.Repet(signal, repet_type=nussl.RepetType.DEFAULT, min_period=1, period=period_complex, max_period=len(beat_spectrum))
    repet.update_periods()

    print period_complex
    print repet.period

    repet.run()
    bg_complex, fg_complex = repet.make_audio_signals()

    return bg_simple, fg_simple, bg_complex, fg_complex

def compute_beat_spectrum_and_suggested_period(X, window_size=None, window_type=None):
    signal = nussl.AudioSignal(audio_data_array=X)
    win = nussl.WindowAttributes(signal.sample_rate)

    if window_size != None:
        win.window_length = window_size
    if window_type != None:
        win.window_type = window_type

    result = nussl.FftUtils.f_stft(X, window_attributes=win)
    beat_spectrum = nussl.Repet.compute_beat_spectrum(result[0])
    return beat_spectrum, nussl.Repet.find_repeating_period(beat_spectrum, 1, X.shape[0])

def insert_row(table, values):
    conn = sqlite3.connect('repet.db')
    cursor = conn.cursor()
    t = (values[0], values[1], values[2], values[3], values[4], values[5], values[6], values[7], values[8], values[9], values[10], values[11])
    cursor.execute('insert into {} (window_size, window_type, period, bg_sdr, fg_sdr, fg_file, bg_file, period_min, period_max, suggested_period, default_fg_sdr, default_bg_sdr) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'.format(table), t)
    conn.commit()
    conn.close()

def insert_nearest_neighbors(values):
    conn = sqlite3.connect('repet.db')
    cursor = conn.cursor()
    cursor.execute('insert into nearest_neighbor (window_size, window_type, period, standard_deviation, bpm, fg_file, bg_file, period_min, period_max, suggested_period) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', values)
    conn.commit()
    conn.close()

def all_repet_params(fg_input_directory, fg_file_name_base, bg_input_directory, bg_file_name_base, output_directory, sample_rate):
    '''
    Creates all combinations of foreground and background files and runs a large series of REPET parameters on them

    Parameters
    ----------
    fg_input_directory : str
        input directory 
    fg_file_name_base : str
        the base string for a file name
    bg_input_directory : str
        input directory 
    bg_file_name_base : str
        the base string for a file name
    output_directory : str
        where the results will be stored
    sample_rate : int
        sample rate in number of samples per seconds
    '''
    window_sizes = [256, 512, 1024, 2048, 4096, 8192, 16384]
    window_types = [nussl.WindowType.HAMMING, nussl.WindowType.RECTANGULAR, nussl.WindowType.HANN, nussl.WindowType.BLACKMAN]
    
    for i in range(0, 5):
        for j in range(1, 5):
            fg_file_name = fg_file_name_base + ('%02d.wav' % i)
            bg_file_name = bg_file_name_base + ('%02d.wav' % j)
            fg, sr = librosa.load(os.path.join(fg_input_directory, fg_file_name), sr=sample_rate)
            bg, sr = librosa.load(os.path.join(bg_input_directory, bg_file_name), sr=sample_rate)

            bg = bg[:fg.shape[0]]
            mix = fg + bg

            # create the directory for the output files
            # new_directory = os.path.join(output_directory, 'fg-%02d-bg-%02d' % (i, j))

            # if not os.path.exists(new_directory):
            #     os.makedirs(new_directory)
            
            for window_size in window_sizes:
                for window_type in window_types:
                    bg_simple, fg_simple, bg_complex, fg_complex = run_repet(mix, window_size=window_size, window_type=window_type)

                    fg_simple_result = mir_eval.separation.bss_eval_sources(fg, fg_simple.audio_data)
                    bg_simple_result = mir_eval.separation.bss_eval_sources(bg, bg_simple.audio_data)

                    fg_complex_result = mir_eval.separation.bss_eval_sources(fg, fg_complex.audio_data)
                    bg_complex_result = mir_eval.separation.bss_eval_sources(bg, bg_complex.audio_data)

                    print 'window_size: ', window_size, 'window_type: ', window_type, 'simple_bg_sdr: ', bg_simple_result[0][0], 'simple_fg_sdr: ', fg_simple_result[0][0], 'complex_bg_sdr: ', bg_complex_result[0][0], 'complex_fg_sdr: ', fg_complex_result[0][0]

                        # values = (window_size, window_type, period, bg_result[0][0], fg_result[0][0], fg_file_name, bg_file_name, period_min, period_max, suggested_period, default_fg_result[0][0], default_bg_result[0][0])

                        # print values
                        # insert_row('repet', values)

def all_nearest_neighbor(fg_input_directory, fg_file_name_base, bg_input_directory, bg_file_name_base, output_directory, sample_rate):
    '''
    Creates all combinations of foreground and background files and runs a large series of REPET parameters on them

    fg_input_directory : str
        input directory 
    fg_file_name_base : str
        the base string for a file name
    bg_input_directory : str
        input directory 
    bg_file_name_base : str
        the base string for a file name
    output_directory : str
        where the results will be stored
    sample_rate : int
        sample rate in number of samples per seconds
    '''
    window_sizes = [256, 512, 1024, 2048, 4096, 8192]
    window_types = [nussl.WindowType.HAMMING, nussl.WindowType.RECTANGULAR, nussl.WindowType.HANN, nussl.WindowType.BLACKMAN]
    # window_sizes = [256]
    # window_types = [nussl.WindowType.HAMMING]
    # period = [i for i in range(0, 1000)]
    for i in range(0, 1):
        for j in range(1, 2):
            fg_file_name = fg_file_name_base + ('%02d.wav' % i)
            bg_file_name = bg_file_name_base + ('%02d.wav' % j)
            fg, sr = librosa.load(os.path.join(fg_input_directory, fg_file_name), sr=sample_rate)
            bg, sr = librosa.load(os.path.join(bg_input_directory, bg_file_name), sr=sample_rate)

            bg = bg[:fg.shape[0]]
            mix = fg + bg
            
            for window_size in window_sizes:
                for window_type in window_types:

                    bs, suggested_period = compute_beat_spectrum_and_suggested_period(mix, window_size=window_size, window_type=window_type)
                    period_min = suggested_period / 8
                    period_max = suggested_period

                    sd = beat_spectrum_std(bs)
                    tempo, beats = librosa.beat.beat_track(mix)

                    periods = [suggested_period / 8, suggested_period / 7, suggested_period / 6, suggested_period / 5, suggested_period / 4, suggested_period / 3, suggested_period / 2, suggested_period]
                    for period in periods:
                        
                        values = (window_size, window_type, period, sd, tempo, fg_file_name, bg_file_name, period_min, period_max, suggested_period)

                        print values
                        insert_nearest_neighbors(values)

def beat_spectrum_std(beat_spectrum):
    total = np.max(beat_spectrum)
    bin_separation = total / 1000
    quantized = np.divide(beat_spectrum, bin_separation)
    histogram = {}
    for x in quantized:
        if x in histogram:
            histogram[x] += 1
        else:
            histogram[x] = 1

    return np.std(quantized)


# if __name__ == '__main__':
    # all_repet_params('../fg/processed/', 'fg-', '../bg/processed/', 'bg-', '',  44100)
    # all_nearest_neighbor('../fg/processed/', 'fg-', '../bg/processed/', 'bg-', '',  44100)
    # pre_process_files()
    
